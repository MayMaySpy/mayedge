"""One Trail job. Rule ids are docs/trail-rules.md.

The desk follows the best price and either moves a venue Stop (an exit on Mark)
or fires its own Market order (an entry, or an exit on Last, with a venue backstop).
The Position on the account feed is the evidence for every fill (ADR 0003).
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from decimal import Decimal
from typing import Any

from mayedge.algos import common
from mayedge.algos.chase.state import ACTIVE_STATUSES, ChaseStatus
from mayedge.algos.ledger import Clip, Ledger
from mayedge.algos.planner import venue
from mayedge.algos.role_job import RoleJob
from mayedge.algos.trail import engine
from mayedge.algos.trail.config import (
    ACK_GRACE_MS,
    CANCEL_WAIT_S,
    CANCEL_WAIT_TRIES,
    MARKET_GRACE_MS,
    MISSING_GRACE_MS,
    RATE_LIMIT_COOLDOWN_MS,
)
from mayedge.algos.trail.engine import Follow, Point, Side
from mayedge.algos.trail.plan import (
    ALGO_ID,
    ALGO_VERSION,
    Resolved,
    TrailParams,
    TrailRefused,
    check_distance,
    follow_of,
)
from mayedge.algos.trail.state import TrailBookView, TrailState
from mayedge.config import settings
from mayedge.lighter.coi import next_manual_client_order_index
from mayedge.numbers import check_notional, fmt_decimal
from mayedge.rows import is_obj, obj

logger = logging.getLogger(__name__)

ZERO = Decimal("0")


def _wrong_side(e: Exception) -> bool:
    return "wrong side of mark" in str(e)


class TrailRunner(RoleJob[TrailBookView, TrailState]):
    LABEL = "trail"
    CANCEL_WAIT_TRIES = CANCEL_WAIT_TRIES
    CANCEL_WAIT_S = CANCEL_WAIT_S
    ACK_GRACE_MS = ACK_GRACE_MS
    MISSING_GRACE_MS = MISSING_GRACE_MS
    RATE_LIMIT_COOLDOWN_MS = RATE_LIMIT_COOLDOWN_MS

    def __init__(self, book: TrailBookView) -> None:
        super().__init__(book, TrailState())

    @property
    def kind(self) -> str:
        p = self._state.params
        return p.kind if p else ""

    # ── shape ────────────────────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        st = self._state
        p = st.params
        params_json = p.to_json() if p else {}
        runtime = st.runtime_json()
        fire = self._latest("fire")
        return {
            "type": "algo",
            "id": ALGO_ID,
            "algo_type": ALGO_ID,
            "version": ALGO_VERSION,
            "algo_id": st.algo_id or None,
            "status": st.status.value,
            "market_index": st.market_index,
            "symbol": st.symbol,
            "reduce_only": bool(p and p.kind != "entry"),
            "side": st.side,
            "qty": fmt_decimal(st.qty),
            "display_qty": None,
            "offset_bps": None,
            "price_floor": None,
            "price_ceiling": None,
            "remaining": None,
            "filled": fmt_decimal(fire.filled) if fire else "0",
            "quote_action": "rest" if st.status == ChaseStatus.RUNNING else "pause",
            "reason": st.reason,
            "rest_price": fmt_decimal(st.venue_trigger),
            "rest_qty": None,
            "working_coi": None,
            "working_order_index": None,
            "error": st.error,
            "created_at": st.created_at or None,
            "params_json": {**params_json, "runtime": {"trail": runtime}},
            "trail": {
                **runtime,
                "kind": p.kind if p else None,
                "reference": p.reference if p else None,
                "distance": fmt_decimal(p.distance) if p else None,
                "distance_kind": p.distance_kind if p else None,
                "activation": fmt_decimal(p.activation) if p else None,
                "backstop": bool(p and p.kind != "entry" and p.reference == "last"),
                "clip_roles": {
                    str(c.client_order_index): st.roles.get(c.seq, "") for c in st.ledger.clips
                },
            },
            **st.ledger.to_dict(),
        }

    def hydrate_from_row(self, row: dict[str, Any]) -> None:
        raw: object = row.get("params_json") or {}
        if not is_obj(raw):
            raise ValueError(f"unrecoverable trail row {row.get('algo_id')}: no params")
        params = TrailParams.from_json(raw)
        runtime = obj(obj(raw.get("runtime")).get("trail"))
        status = ChaseStatus.of(row.get("status"))
        st = TrailState(
            status=status,
            params=params,
            market_index=int(row.get("market_index") or 0),
            symbol=str(row.get("symbol") or ""),
            algo_id=str(row.get("algo_id") or ""),
            created_at=int(row.get("created_at") or 0),
            reason=row.get("reason"),
            error=row.get("error"),
            ledger=Ledger.from_row(row),
        )
        st.load_runtime(runtime)
        self._state = st

    # ── reads ────────────────────────────────────────────────────────────

    def _follow(self) -> Follow:
        st = self._state
        assert st.params is not None
        return follow_of(st.params, st.side, self._tick(), floor=st.floor)

    def _held(self) -> Decimal:
        """The Position on the side this Trail closes (or opens), negative when the other way."""
        size = venue.position(self._exec(), self._state.market_index).size
        # A sell closes a long and opens a short.
        long_side = self._state.side == "sell"
        exit_kind = self.kind != "entry"
        sign = 1 if long_side == exit_kind else -1
        return size * sign

    def _feed_live(self) -> bool:
        health = self._exec().feed_health
        if health is None:
            return True
        return health().get("market_ws") == "live"

    # ── clips ────────────────────────────────────────────────────────────

    def _clip_side(self, role: str) -> Side:
        del role
        return self._state.side

    def _trade_counts(self, clip: Clip) -> bool:
        """Only a fired Market order fills from the tape. The Stop is read off the Position."""
        return self._role(clip) == "fire"

    # ── sends ────────────────────────────────────────────────────────────

    async def _place_stop(self, trigger: Decimal) -> bool:
        """TS1, TT3, L2 and V1: the venue Stop at ``trigger``. False when mark has passed it."""
        st = self._state
        ex = self._exec()
        if ex.create_trigger_leg is None:
            raise RuntimeError("trigger orders are not wired")
        p = st.params
        assert p is not None
        clip = self._place("stop", price=trigger, qty=st.qty)
        try:
            await ex.create_trigger_leg(
                st.market_index,
                st.side,
                fmt_decimal(st.qty) or "0",
                role="sl",
                kind="market",
                trigger=fmt_decimal(trigger) or "0",
                slippage=p.slippage,
                client_order_index=clip.client_order_index,
            )
        except Exception as e:
            clip.status = "cancelled"
            clip.closed_at = common.now_ms()
            if isinstance(e, ValueError) and _wrong_side(e):
                return False
            raise
        st.venue_trigger = trigger
        st.last_move_ms = common.now_ms()
        if self.kind == "tp":
            st.held_before = self._held()
        return True

    async def _move_stop(self, clip: Clip, trigger: Decimal) -> bool:
        """F6: Amend the venue Stop. False when mark has passed the new trigger."""
        st = self._state
        await self._await_order_index(clip)
        if not clip.order_index:
            return True
        ex = self._exec()
        if ex.amend_trigger_leg is None:
            raise RuntimeError("trigger amend is not wired")
        p = st.params
        assert p is not None
        try:
            await ex.amend_trigger_leg(
                st.market_index,
                clip.order_index,
                st.side,
                role="sl",
                kind="market",
                trigger=fmt_decimal(trigger) or "0",
                slippage=p.slippage,
            )
        except ValueError as e:
            if _wrong_side(e):
                return False
            raise
        clip.price = trigger
        st.venue_trigger = trigger
        st.last_move_ms = common.now_ms()
        return True

    async def _fire(self, price: Decimal, *, why: str) -> None:
        """TE1, L1 and V2: a Market order for this Trail's size."""
        st = self._state
        p = st.params
        assert p is not None
        held = self._held()
        if p.kind == "entry":
            qty = st.qty
        elif p.kind == "stop":
            qty = held
        else:
            qty = min(st.qty, held)
        if qty <= 0:
            return
        if p.kind == "entry":
            check_notional(qty, price, settings.max_order_notional)
        clip = self._place("fire", price=price, qty=qty)
        st.held_before = held
        st.fired_at = common.now_ms()
        st.fired_price = price
        try:
            await self._exec().create_market_order(
                market_index=st.market_index,
                side=st.side,
                size=fmt_decimal(qty),
                slippage=p.slippage,
                reduce_only=p.kind != "entry",
                client_order_index=clip.client_order_index,
            )
        except Exception:
            clip.status = "cancelled"
            clip.closed_at = common.now_ms()
            st.fired_at = None
            raise
        st.reason = why

    # ── loop ─────────────────────────────────────────────────────────────

    async def start(
        self,
        *,
        algo_id: str,
        market_index: int,
        symbol: str,
        params: TrailParams,
        resolved: Resolved,
        replaced: list[dict[str, Any]] | None = None,
    ) -> None:
        now = common.now_ms()
        self._state = TrailState(
            status=ChaseStatus.RUNNING,
            params=params,
            side=resolved.side,
            qty=resolved.qty,
            floor=resolved.start,
            market_index=market_index,
            symbol=symbol,
            algo_id=algo_id,
            created_at=now,
        )
        st = self._state
        if params.kind == "entry" and params.expiry_min:
            st.deadline_ms = now + params.expiry_min * 60_000
        f = self._follow()
        st.point = engine.follow(f, Point(), resolved.mark)
        st.reason = "following" if st.point.active else "waiting for the Activation"
        try:
            if params.kind == "stop":
                assert st.point.trigger is not None
                at = self._venue_price(f, st.point)
                if not await self._place_stop(at):
                    raise TrailRefused("S3", "Mark is already past the start")
                # TS4: the stop is on before the Tickets it replaces come off.
                left = await self._pull_tickets(replaced or [])
                if left:
                    st.reason = f"{left} replaced Stop still live"
        except Exception:
            await self._cancel_all()
            raise
        self._publish()
        self._task = asyncio.create_task(self._run())

    async def _evaluate(self) -> None:
        async with self._lock:
            st = self._state
            if st.status != ChaseStatus.RUNNING:
                return
            ex = self._exec()
            if not ex.orders_hydrated():
                return
            now = common.now_ms()
            if not self._feed_live():
                # F10: no price to follow. What is on the venue stays.
                self._prints.clear()
                if st.following:
                    st.following = False
                    self._publish()
                return
            st.following = True
            self._drain_trades(now)
            self._sync_open(now)
            if self.kind == "entry":
                await self._evaluate_entry(now)
            else:
                await self._evaluate_exit(now)
            if st.status in ACTIVE_STATUSES:
                self._publish()

    def _done(self, reason: str) -> None:
        st = self._state
        st.status = ChaseStatus.DONE
        st.reason = reason
        self._book.finish(self)

    async def _evaluate_entry(self, now: int) -> None:
        st = self._state
        fire = self._latest("fire")
        if fire is not None:
            # TE3: the Position or the trades say how much filled.
            moved = max(ZERO, self._held() - st.held_before)
            filled = max(min(fire.filled, st.qty), min(moved, st.qty))
            half = self._qty_step() / 2
            if filled >= st.qty - half or now - fire.placed_at >= MARKET_GRACE_MS:
                fire.filled = max(fire.filled, filled)
                fire.status = "filled" if filled > 0 else "cancelled"
                fire.closed_at = now
                self._done(f"filled {fmt_decimal(filled)}" if filled > 0 else "entry did not fill")
            return
        if st.deadline_ms and now >= st.deadline_ms:
            self._done("entry expired")  # TE2
            return
        f = self._follow()
        for px in self._prices():
            st.point = engine.follow(f, st.point, px)
            trigger = st.point.trigger
            if st.point.active and trigger is not None and engine.crossed(f, trigger, px):
                await self._fire(px, why=f"fired at {fmt_decimal(px)}")  # TE1
                return
        if st.point.active:
            st.reason = "following"

    def _venue_price(self, f: Follow, point: Point) -> Decimal:
        """Where the venue Stop belongs: the trigger on Mark, one step behind it on Last (L2)."""
        st = self._state
        assert st.params is not None and point.trigger is not None
        if st.params.reference == "mark":
            return point.trigger
        return engine.backstop(f, point.trigger, point.best or point.trigger)

    async def _evaluate_exit(self, now: int) -> None:
        st = self._state
        p = st.params
        assert p is not None
        held = self._held()
        if held <= 0:
            # TS5 and TT5: flat, by this Trail, another order or the operator.
            self._flat_since = self._flat_since or now
            if now - self._flat_since < MISSING_GRACE_MS:
                return
            await self._cancel_all()
            self._done("flat")
            return
        self._flat_since = None
        half = self._qty_step() / 2

        fire = self._latest("fire")
        if fire is not None and fire.status == "live":
            closed = st.held_before - held
            if p.kind == "tp" and closed >= fire.qty - half:
                fire.status = "filled"
                fire.filled = max(fire.filled, fire.qty)
                fire.closed_at = now
                await self._cancel_all()  # L3: the backstop comes off
                self._done(st.reason or "fired")
                return
            if now - fire.placed_at < MARKET_GRACE_MS:
                return
            # The close did not do it. Keep following; the venue Stop still holds.
            fire.status = "cancelled"
            fire.closed_at = now
            st.fired_at = None

        stop = self._live("stop")
        if stop is not None and self._gone(stop, now):
            if p.kind == "tp" and st.held_before - held >= st.qty - half:
                stop.status = "filled"
                stop.filled = stop.qty
                stop.closed_at = now
                self._done("filled")  # TT5
                return
            # V1: the Position is open and its stop is gone. It goes back on below.
            stop.status = "cancelled"
            stop.closed_at = now
            stop = None

        f = self._follow()
        for px in self._prices():
            st.point = engine.follow(f, st.point, px)
            trigger = st.point.trigger
            if p.reference == "last" and trigger is not None and engine.crossed(f, trigger, px):
                await self._fire(px, why=f"fired at {fmt_decimal(px)}")  # L1
                return
        point = st.point
        if point.trigger is None:
            return  # TT1: a Take Profit waits off the venue
        if point.active:
            st.reason = "following"
        wanted = self._venue_price(f, point)
        if stop is None:
            if not await self._place_stop(wanted):
                await self._fire(self._mark(), why="mark passed the stop: closed at market")  # V2
            return
        if st.venue_trigger is None:
            st.venue_trigger = stop.price
        if not engine.move_due(
            f,
            venue=st.venue_trigger,
            wanted=wanted,
            best=point.best or wanted,
            now_ms=now,
            last_move_ms=st.last_move_ms,
        ):
            return
        if not self._book.take_amend(st.market_index, now):
            return  # F7: the Market's Amend budget is spent this minute
        if not await self._move_stop(stop, wanted):
            await self._fire(self._mark(), why="mark passed the stop: closed at market")  # V2

    # ── operator ─────────────────────────────────────────────────────────

    async def unpause(self) -> None:
        st = self._state
        if st.status not in (ChaseStatus.PAUSED, ChaseStatus.ERROR):
            return
        st.status = ChaseStatus.RUNNING
        st.error = None
        st.reason = "following" if st.point.active else "waiting for the Activation"
        self._running_again()

    async def edit(self, params: TrailParams) -> None:
        """F4: a new distance or Activation. The trigger never moves back."""
        st = self._state
        old = st.params
        assert old is not None
        if params.kind != old.kind:
            raise TrailRefused("S3", "An edit keeps the kind")
        if params.reference != old.reference:
            raise TrailRefused("S3", "An edit keeps the Reference")
        ctx, _ = venue.market_context(self._exec(), st.market_index)
        check_distance(params, ctx)
        async with self._lock:
            activation = old.activation if st.point.active else params.activation
            if not st.point.active and activation is not None:
                f = follow_of(params, st.side, ctx.tick, floor=st.floor)
                if engine.reached(f, ctx.mark, activation):
                    raise TrailRefused("S3", "Mark is already past the Activation")
            if old.kind == "tp" and activation is None:
                raise TrailRefused("TT1", "Set the Activation price")
            st.params = dataclasses.replace(
                old,
                distance=params.distance,
                distance_kind=params.distance_kind,
                activation=activation,
                slippage=params.slippage,
                expiry_min=params.expiry_min if old.kind == "entry" else old.expiry_min,
            )
            if old.kind == "entry" and params.expiry_min:
                st.deadline_ms = st.created_at + params.expiry_min * 60_000
            st.reason = "edited"
        self._publish()
        self._wake.set()

    async def stop(self, *, keep_stop: bool = False) -> None:
        """S5: every Clip comes off. With keep_stop, a plain Stop Ticket goes on first."""
        await self._halt()
        st = self._state
        if st.status not in ACTIVE_STATUSES:
            return
        kept = False
        if keep_stop and self.kind == "stop" and self._held() > 0:
            kept = await self._keep_stop()
        complete = await self._cancel_all()
        self._end_stop(complete, "stopped, Stop Ticket kept" if kept else "stopped")

    async def _keep_stop(self) -> bool:
        st = self._state
        p = st.params
        ex = self._exec()
        trigger = st.point.trigger or st.venue_trigger
        if p is None or trigger is None or ex.create_trigger_leg is None:
            return False
        try:
            await ex.create_trigger_leg(
                st.market_index,
                st.side,
                "0",
                role="sl",
                kind="market",
                trigger=fmt_decimal(trigger) or "0",
                slippage=p.slippage,
                client_order_index=next_manual_client_order_index(),
            )
        except ValueError as e:
            logger.warning("trail %s: Stop Ticket not kept: %s", st.algo_id, e)
            return False
        return True

    async def drain_for_shutdown(self) -> None:
        """V5: the venue Stop stays while the desk is down."""
        await self._halt()
        self._stop.clear()
