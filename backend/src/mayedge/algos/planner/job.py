"""One Planner job. Rule ids are docs/planner-rules.md.

The Position on the account feed is the evidence for the entry and for every
exit: Planner never treats a quiet book as a fill on its own (E7).
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from decimal import Decimal
from typing import Any

from mayedge.algos import common
from mayedge.algos.chase.iceberg import MarketView
from mayedge.algos.chase.state import ACTIVE_STATUSES, ChaseStatus
from mayedge.algos.ladder.plan import Rung
from mayedge.algos.ledger import Clip, Ledger
from mayedge.algos.planner import entry as entry_phase
from mayedge.algos.planner import manage as manage_phase
from mayedge.algos.planner import venue
from mayedge.algos.planner.config import (
    ACK_GRACE_MS,
    CANCEL_WAIT_S,
    CANCEL_WAIT_TRIES,
    MISSING_GRACE_MS,
    RATE_LIMIT_COOLDOWN_MS,
)
from mayedge.algos.planner.plan import (
    ALGO_ID,
    ALGO_VERSION,
    Plan,
    PlannedStep,
    PlannedTarget,
    PlannerParams,
    PlanRefused,
    Side,
    check_stop_live,
    check_targets_live,
    entry_follow,
    plan_steps,
    price_plan,
    stop_price,
)
from mayedge.algos.planner.state import PlannerBookView, PlannerState
from mayedge.algos.role_job import RoleJob
from mayedge.algos.trail import engine
from mayedge.algos.trail.engine import Follow, Point
from mayedge.config import settings
from mayedge.numbers import check_notional, fmt_decimal
from mayedge.rows import is_obj, obj

logger = logging.getLogger(__name__)

ZERO = Decimal("0")


def _sign(side: str) -> int:
    return 1 if side == "buy" else -1


class PlannerRunner(RoleJob[PlannerBookView, PlannerState]):
    LABEL = "planner"
    CANCEL_WAIT_TRIES = CANCEL_WAIT_TRIES
    CANCEL_WAIT_S = CANCEL_WAIT_S
    ACK_GRACE_MS = ACK_GRACE_MS
    MISSING_GRACE_MS = MISSING_GRACE_MS
    RATE_LIMIT_COOLDOWN_MS = RATE_LIMIT_COOLDOWN_MS

    def __init__(self, book: PlannerBookView) -> None:
        super().__init__(book, PlannerState())
        self._mismatch_since: int | None = None
        # Roles Planner gave up placing after a refusal, so it does not resend every tick.
        self._gave_up: set[str] = set()
        # E10: when a Chase entry's Clip last moved.
        self._entry_moved_ms = 0
        # E13, EL1: when a Chase entry's Clip or a Ladder rung last left the book unexplained.
        self._entry_vanished_ms = 0

    # ── shape ────────────────────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        st = self._state
        p = st.params
        plan = st.plan
        entry = self._latest("entry")
        params_json = p.to_json() if p else {}
        runtime = st.runtime_json()
        # E10: a Chase entry's band draws on the chart while it works.
        band = p.entry_chase if p and st.phase == "entering" and p.entry_type == "chase" else None
        return {
            "type": "algo",
            "id": ALGO_ID,
            "algo_type": ALGO_ID,
            "version": ALGO_VERSION,
            "algo_id": st.algo_id or None,
            "status": st.status.value,
            "market_index": st.market_index,
            "symbol": st.symbol,
            "reduce_only": False,
            "side": p.side if p else None,
            "qty": fmt_decimal(plan.size) if plan else None,
            "display_qty": None,
            "offset_bps": None,
            # The stop and targets are on the chart as orders, not as a band.
            "price_floor": fmt_decimal(band.low) if band else None,
            "price_ceiling": fmt_decimal(band.high) if band else None,
            "remaining": fmt_decimal(max(ZERO, plan.size - st.entry_filled)) if plan else None,
            "filled": fmt_decimal(st.entry_filled),
            "quote_action": "rest" if st.status == ChaseStatus.RUNNING else "pause",
            "reason": st.reason,
            "rest_price": fmt_decimal(entry.price) if entry and entry.status == "live" else None,
            "rest_qty": fmt_decimal(entry.remaining) if entry and entry.status == "live" else None,
            "working_coi": entry.client_order_index if entry and entry.status == "live" else None,
            "working_order_index": (
                str(entry.order_index)
                if entry and entry.status == "live" and entry.order_index
                else None
            ),
            "error": st.error,
            "created_at": st.created_at or None,
            "params_json": {**params_json, "runtime": {"planner": runtime}},
            "planner": {**runtime, "clip_roles": self._clip_roles()},
            **st.ledger.to_dict(),
        }

    def _clip_roles(self) -> dict[str, str]:
        return {
            str(c.client_order_index): self._state.roles.get(c.seq, "")
            for c in self._state.ledger.clips
        }

    def hydrate_from_row(self, row: dict[str, Any]) -> None:
        raw: object = row.get("params_json") or {}
        if not is_obj(raw):
            raise ValueError(f"unrecoverable planner row {row.get('algo_id')}: no params")
        params = PlannerParams.from_json(raw)
        runtime = obj(obj(raw.get("runtime")).get("planner"))
        status = ChaseStatus.of(row.get("status"))
        st = PlannerState(
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
        if st.plan is None:
            raise ValueError(f"unrecoverable planner row {row.get('algo_id')}: no plan")
        if not st.plan.steps and params.stop_steps != "off":
            # Saved before Stop steps were drawn into the plan.
            st.plan = dataclasses.replace(
                st.plan,
                steps=plan_steps(
                    params.stop_steps,
                    st.plan.targets,
                    size=st.plan.size,
                    breakeven=st.plan.breakeven,
                ),
            )
        self._state = st

    # ── clips ────────────────────────────────────────────────────────────

    def _clip_side(self, role: str) -> Side:
        return self._side() if role == "entry" else self._close_side()

    def _follows_prices(self) -> bool:
        p = self._state.params
        return p is not None and p.trails()

    def _trade_counts(self, clip: Clip) -> bool:
        """The stop fills off the Position, so the tape counts for every other Clip."""
        return self._role(clip) != "stop"

    def _book_fills(self, clip: Clip) -> bool:
        return self._role(clip) != "stop"

    def _absence_counts(self, clip: Clip) -> bool:
        """An entry is judged gone only once it was seen. A target or stop may
        fill before the feed ever shows it, so its absence counts from now."""
        return self._role(clip) != "entry" or clip.seen_on_book

    def _tp_clips(self) -> list[Clip]:
        return [c for c in self._state.ledger.clips if self._role(c).startswith("tp")]

    def _tp_filled(self) -> Decimal:
        return sum((min(c.filled, c.qty) for c in self._tp_clips()), ZERO)

    def _side(self) -> Side:
        p = self._state.params
        return p.side if p else "buy"

    def _close_side(self) -> Side:
        return "sell" if self._side() == "buy" else "buy"

    # ── sends ────────────────────────────────────────────────────────────

    async def _send_entry(self) -> None:
        st = self._state
        p, plan = st.params, st.plan
        assert p is not None and plan is not None
        clip = self._place("entry", price=plan.entry, qty=plan.size)
        ex = self._exec()
        try:
            if p.entry_type in ("market", "trail"):
                await ex.create_market_order(
                    market_index=st.market_index,
                    side=p.side,
                    size=fmt_decimal(plan.size),
                    slippage=p.slippage,
                    reduce_only=False,
                    client_order_index=clip.client_order_index,
                )
            else:
                await ex.create_limit_order(
                    market_index=st.market_index,
                    side=p.side,
                    size=fmt_decimal(plan.size),
                    price=fmt_decimal(plan.entry),
                    time_in_force="gtt",
                    reduce_only=False,
                    client_order_index=clip.client_order_index,
                )
        except Exception:
            clip.status = "cancelled"
            clip.closed_at = common.now_ms()
            raise

    async def _send_trigger(
        self, clip: Clip, *, role: str, kind: str, size: Decimal, trigger: Decimal
    ) -> None:
        ex = self._exec()
        if ex.create_trigger_leg is None:
            raise RuntimeError("trigger orders are not wired")
        p = self._state.params
        try:
            await ex.create_trigger_leg(
                self._state.market_index,
                self._close_side(),
                fmt_decimal(size) or "0",
                role=role,
                kind=kind,
                trigger=fmt_decimal(trigger) or "0",
                price=fmt_decimal(trigger) if kind == "limit" else None,
                slippage=p.slippage if p else 0.01,
                client_order_index=clip.client_order_index,
            )
        except Exception:
            clip.status = "cancelled"
            clip.closed_at = common.now_ms()
            raise

    async def _place_stop(self) -> None:
        """E2: one Stop Market tied to the Position (size 0), P9."""
        st = self._state
        assert st.plan is not None
        trigger = st.stop_trigger if st.stop_trigger is not None else st.plan.stop
        clip = self._place("stop", price=trigger, qty=ZERO)
        try:
            await self._send_trigger(clip, role="sl", kind="market", size=ZERO, trigger=trigger)
        except ValueError as e:
            if "wrong side of mark" not in str(e):
                raise
            await self._close_at_market()
            return
        st.stop_trigger = trigger

    async def _close_at_market(self) -> None:
        """E8: mark is through the stop, so the venue will not take one. Do what it would."""
        st = self._state
        pos, _ = self._held()
        if pos <= 0:
            return
        clip = self._place("close", price=self._mark(), qty=pos)
        p = st.params
        await self._exec().create_market_order(
            market_index=st.market_index,
            side=self._close_side(),
            size=fmt_decimal(pos),
            slippage=p.slippage if p else 0.01,
            reduce_only=True,
            client_order_index=clip.client_order_index,
        )
        self._gave_up.add("stop")
        st.reason = "stop reached: closed at market"

    async def _place_targets(self) -> None:
        """E3 and P9: each target as its order type, at its price. Skips what is placed or done."""
        st = self._state
        assert st.plan is not None
        for t in st.plan.targets:
            role = f"tp{t.index}"
            if role in self._gave_up or t.order == "trail":
                continue
            clips = [c for c in st.ledger.clips if self._role(c) == role]
            left = t.qty - sum((c.filled for c in clips), ZERO)
            live = [c for c in clips if c.status == "live"]
            if live:
                # M6: a resize leaves the live target at its old size. Put it back on at the new one.
                if not manage_phase._wrong_size(live[0], left, self._qty_step() / 2):
                    continue
                if not await self._cancel_clip(live[0]):
                    continue
            if left <= 0:
                continue
            try:
                if t.order == "limit":
                    await self._rest_target(role, price=t.price, qty=left)
                    continue
                clip = self._place(role, price=t.price, qty=left)
                await self._send_trigger(clip, role="tp", kind="limit", size=left, trigger=t.price)
            except ValueError as e:
                if t.order == "limit" or "wrong side of mark" not in str(e):
                    self._gave_up.add(role)
                    st.reason = f"target {t.index} refused: {e}"
                    continue
                # Mark ran past a Trigger before it went on: a resting limit
                # at the target fills at it or better.
                await self._rest_target(role, price=t.price, qty=left)

    async def _rest_target(self, role: str, *, price: Decimal, qty: Decimal) -> None:
        """A reduce-only limit on the book at the target (P9 Limit)."""
        st = self._state
        clip = self._place(role, price=price, qty=qty)
        try:
            await self._exec().create_limit_order(
                market_index=st.market_index,
                side=self._close_side(),
                size=fmt_decimal(qty),
                price=fmt_decimal(price),
                time_in_force="gtt",
                reduce_only=True,
                client_order_index=clip.client_order_index,
            )
        except Exception:
            clip.status = "cancelled"
            clip.closed_at = common.now_ms()
            raise

    # ── evidence ─────────────────────────────────────────────────────────

    def _held(self) -> tuple[Decimal, Decimal | None]:
        """Position size on Planner's side (negative when the other way), and its entry."""
        held = venue.position(self._exec(), self._state.market_index)
        return held.size * _sign(self._side()), held.entry

    # ── loop ─────────────────────────────────────────────────────────────

    async def start(
        self,
        *,
        algo_id: str,
        market_index: int,
        symbol: str,
        params: PlannerParams,
        plan: Plan,
        replaced: list[dict[str, Any]] | None = None,
    ) -> None:
        self._state = PlannerState(
            status=ChaseStatus.RUNNING,
            phase="entering" if params.mode == "enter" else "managing",
            params=params,
            plan=plan,
            market_index=market_index,
            symbol=symbol,
            algo_id=algo_id,
            created_at=common.now_ms(),
        )
        st = self._state
        try:
            if params.mode == "enter":
                check_notional(plan.size, plan.entry, settings.max_order_notional)
                if params.entry_type in ("limit", "trail", "chase", "ladder") and params.expiry_min:
                    st.entry_deadline_ms = st.created_at + params.expiry_min * 60_000
                if params.entry_type in ("chase", "ladder"):
                    # E10, EL1: the first Clips go on at the first look at the book.
                    st.reason = "entry working"
                elif params.entry_type == "trail":
                    # E9: the desk holds the entry until the price comes back.
                    f = entry_follow(params, self._tick())
                    st.trails["entry"] = engine.follow(f, Point(), self._mark())
                    st.reason = (
                        "entry following"
                        if st.trails["entry"].active
                        else "entry waits for its Activation"
                    )
                else:
                    await self._send_entry()
            else:
                st.entry_filled = plan.size
                st.expected_size = plan.size
                await self._place_stop()
                # S6: the stop is on before the Tickets it replaces come off.
                left = await self._pull_tickets(replaced or [])
                if left:
                    st.reason = f"{left} replaced Stop / Take Profit still live"
                await self._place_targets()
        except Exception:
            await self._cancel_all()
            raise
        self._publish()
        self._task = asyncio.create_task(self._run())

    async def _evaluate(self) -> None:
        async with self._lock:
            if self._state.status not in ACTIVE_STATUSES:
                return
            ex = self._exec()
            if not ex.orders_hydrated():
                return
            now = common.now_ms()
            self._drain_trades(now)
            self._sync_open(now)
            prices = self._prices()
            if self._state.phase == "entering":
                await self._evaluate_entry(now, prices)
            else:
                await self._evaluate_manage(now, prices)
            if self._state.status in ACTIVE_STATUSES:
                self._publish()

    async def _evaluate_entry(self, now: int, prices: list[Decimal]) -> None:
        return await entry_phase._evaluate_entry(self, now, prices)

    async def _entry_over(
        self, now: int, filled: Decimal, avg: Decimal | None, *, closed_at: int | None
    ) -> None:
        """E3 and E6: protect what filled, or end with nothing."""
        st = self._state
        assert st.plan is not None
        if filled <= 0:
            # The account feed may lag the order leaving the book.
            if now - (closed_at or now) < MISSING_GRACE_MS:
                return
            await self._cancel_all()
            st.status = ChaseStatus.DONE
            st.reason = st.reason or "entry did not fill"  # E6
            self._book.finish(self)
            return
        await self._enter_managing(filled, avg or st.plan.entry)

    # ── Chase entry (E10–E15) ────────────────────────────────────────────

    def _chase_view(self) -> MarketView | None:
        ex = self._exec()
        mi = self._state.market_index
        if not ex.is_book_synced(mi):
            return None
        bid_s, ask_s = ex.best_bid_ask(mi)
        ctx, _ = venue.market_context(ex, mi)
        return MarketView(
            bid=venue.dec(bid_s),
            ask=venue.dec(ask_s),
            tick=ctx.tick,
            min_qty=ctx.min_qty,
            qty_step=ctx.qty_step,
        )

    async def _work_chase(self, now: int) -> None:
        return await entry_phase._work_chase(self, now)

    async def _rest_entry(self, price: Decimal, qty: Decimal, now: int) -> str | None:
        return await entry_phase._rest_entry(self, price, qty, now)

    async def _amend_chase(self, clip: Clip, price: Decimal, now: int) -> None:
        return await entry_phase._amend_chase(self, clip, price, now)

    # ── Ladder entry (EL1–EL5) ───────────────────────────────────────────

    async def _work_ladder(self, now: int) -> None:
        return await entry_phase._work_ladder(self, now)

    def _pending_rungs(
        self, rungs: tuple[Rung, ...], clips: list[Clip], half: Decimal
    ) -> list[Rung]:
        return entry_phase._pending_rungs(self, rungs, clips, half)

    def _end(self, reason: str) -> None:
        st = self._state
        st.status = ChaseStatus.DONE
        st.reason = reason
        self._book.finish(self)

    async def _track_entry(self, now: int, prices: list[Decimal]) -> None:
        return await entry_phase._track_entry(self, now, prices)

    async def _fire_entry(self, px: Decimal) -> None:
        return await entry_phase._fire_entry(self, px)

    async def _enter_managing(self, filled: Decimal, avg: Decimal) -> None:
        """P4 and E3: re-draw the targets from the actual entry and put them on."""
        st = self._state
        p, plan = st.params, st.plan
        assert p is not None and plan is not None
        st.phase = "managing"
        st.expected_size = filled
        ctx, _ = venue.market_context(self._exec(), st.market_index)
        try:
            st.plan = price_plan(
                side=p.side,
                entry=avg,
                stop=plan.stop,
                size=filled,
                targets=p.targets,
                ctx=ctx,
                risk_pct=plan.risk_pct,
                stop_steps=p.stop_steps,
                trail_stop=p.trail_stop,
            )
        except PlanRefused as e:
            st.status = ChaseStatus.PAUSED
            st.reason = "re-plan: " + e.message
            return
        await self._place_targets()

    async def _evaluate_manage(self, now: int, prices: list[Decimal]) -> None:
        return await manage_phase._evaluate_manage(self, now, prices)

    def _due_step(self) -> PlannedStep | None:
        return manage_phase._due_step(self)

    async def _take_step(self) -> None:
        return await manage_phase._take_step(self)

    def _step_price(self, step: PlannedStep) -> Decimal:
        return manage_phase._step_price(self, step)

    def _leg_follow(
        self,
        distance: Decimal,
        kind: engine.DistanceKind,
        *,
        activation: Decimal | None,
        floor: Decimal | None,
    ) -> Follow:
        return Follow(
            side=self._close_side(),
            distance=distance,
            distance_kind=kind,
            tick=self._tick(),
            activation=activation,
            floor=floor,
        )

    def _venue_wanted(self, f: Follow, point: Point) -> Decimal:
        """Trail L2: on Last the venue Stop sits one step behind the desk's trigger."""
        p = self._state.params
        assert p is not None and point.trigger is not None
        if p.reference == "mark":
            return point.trigger
        return engine.backstop(f, point.trigger, point.best or point.trigger)

    def _move_due(
        self, role: str, f: Follow, *, venue_at: Decimal, wanted: Decimal, best: Decimal, now: int
    ) -> bool:
        if not engine.move_due(
            f,
            venue=venue_at,
            wanted=wanted,
            best=best,
            now_ms=now,
            last_move_ms=self._state.trail_moves.get(role),
        ):
            return False
        return self._book.take_amend(self._state.market_index, now)

    async def _amend_trigger(self, clip: Clip, trigger: Decimal) -> bool | None:
        """Amend a trailing venue Stop. False when mark has passed it; None if not on the book yet."""
        await self._await_order_index(clip)
        if not clip.order_index:
            return None
        ex = self._exec()
        if ex.amend_trigger_leg is None:
            raise RuntimeError("trigger amend is not wired")
        p = self._state.params
        try:
            await ex.amend_trigger_leg(
                self._state.market_index,
                clip.order_index,
                self._close_side(),
                role="sl",
                kind="market",
                trigger=fmt_decimal(trigger) or "0",
                slippage=p.slippage if p else 0.01,
            )
        except ValueError as e:
            if "wrong side of mark" not in str(e):
                raise
            return False
        clip.price = trigger
        return True

    def _trail_stop_started(self) -> bool:
        st = self._state
        assert st.params is not None and st.plan is not None
        ts = st.params.trail_stop
        if ts is None:
            return False
        if ts.start == "r":
            return True  # its Activation is the R multiple
        targets = st.plan.targets
        if not targets:
            return True  # all Runner: it trails from the fill
        n = targets[-1].index if ts.start == "last" else ts.after
        tp = self._latest(f"tp{n}")
        return tp is not None and tp.status == "filled" and tp.filled >= tp.qty

    async def _trail_stop(self, now: int, prices: list[Decimal]) -> None:
        return await manage_phase._trail_stop(self, now, prices)

    async def _trail_targets(self, now: int, prices: list[Decimal]) -> None:
        return await manage_phase._trail_targets(self, now, prices)

    async def _trail_target(self, t: PlannedTarget, now: int, prices: list[Decimal]) -> None:
        return await manage_phase._trail_target(self, t, now, prices)

    async def _fire_target(self, role: str, live: list[Clip], left: Decimal, px: Decimal) -> None:
        return await manage_phase._fire_target(self, role, live, left, px)

    # ── operator ─────────────────────────────────────────────────────────

    async def unpause(self) -> None:
        """Resume accepts the Position as it is now (M6)."""
        st = self._state
        if st.status not in (ChaseStatus.PAUSED, ChaseStatus.ERROR):
            return
        async with self._lock:
            if st.phase == "managing":
                pos, _ = self._held()
                if pos > 0 and st.expected_size > 0 and pos != st.expected_size:
                    # M6: targets take their share of the Position as it is now.
                    manage_phase.resize_to_position(self, pos)
                elif pos > 0:
                    st.entry_filled = pos + self._tp_filled()
                    st.expected_size = pos
            st.status = ChaseStatus.RUNNING
            st.error = None
            st.reason = None
            self._mismatch_since = None
            self._gave_up.clear()
        self._running_again()

    async def finish_entry(self) -> None:
        """E14: Protect now. The rest of the entry comes off and what filled is managed."""
        st = self._state
        if st.phase != "entering" or st.status not in ACTIVE_STATUSES:
            raise PlanRefused("E14", "There is no entry left to end")
        st.finish_entry = True
        if st.status == ChaseStatus.PAUSED:
            st.status = ChaseStatus.RUNNING
        await self._evaluate()
        self._publish()
        self._ensure_task()

    async def replan(self, params: PlannerParams) -> None:
        """M5: change the stop and the targets of a managed Position, checked as if new."""
        st = self._state
        if st.phase != "managing":
            raise PlanRefused("M5", "Wait for the entry to finish before re-planning")
        old = st.params
        assert old is not None and st.plan is not None
        if params.side != old.side:
            raise PlanRefused("M5", "A re-plan keeps the side")
        async with self._lock:
            ctx, _ = venue.market_context(self._exec(), st.market_index)
            pos, avg = self._held()
            if pos <= 0:
                raise PlanRefused("S4", "No open Position to plan")
            stop = stop_price(params.side, params.stop, ctx.tick)
            check_stop_live(params.side, stop, ctx)
            plan = price_plan(
                side=params.side,
                entry=avg or st.plan.entry,
                stop=stop,
                size=pos,
                targets=params.targets,
                ctx=ctx,
                stop_steps=params.stop_steps,
                trail_stop=params.trail_stop,
            )
            check_targets_live(plan, ctx)
            live_stop = self._live("stop")
            if live_stop is not None and stop != st.stop_trigger:
                await self._await_order_index(live_stop)
                if not live_stop.order_index:
                    raise ValueError("The stop is not on the book yet. Try again")
                ex = self._exec()
                assert ex.amend_trigger_leg is not None
                await ex.amend_trigger_leg(
                    st.market_index,
                    live_stop.order_index,
                    self._close_side(),
                    role="sl",
                    kind="market",
                    trigger=fmt_decimal(stop) or "0",
                    slippage=params.slippage,
                )
                live_stop.price = stop
            for clip in self._tp_clips():
                if clip.status == "live" and not await self._cancel_clip(clip):
                    raise ValueError("A target would not cancel. Try again")
            # Old targets keep their fills under a name the new plan does not use.
            for clip in self._tp_clips():
                st.roles[clip.seq] = "tp-old"
            st.params = dataclasses.replace(params, mode=old.mode)
            st.plan = plan
            st.stop_trigger = stop
            st.entry_filled = pos + self._tp_filled()
            st.expected_size = pos
            # New targets step from the start; M4 still keeps the stop from going back.
            st.steps_done = 0
            # New targets trail from new; the stop keeps its best price (F4).
            st.trails = {k: v for k, v in st.trails.items() if not k.startswith("tp")}
            st.trail_fired = {r for r in st.trail_fired if not r.startswith("tp")}
            st.status = ChaseStatus.RUNNING
            st.error = None
            st.reason = "re-planned"
            self._mismatch_since = None
            self._gave_up.clear()
            await self._place_targets()
        self._publish()
        self._ensure_task()

    async def stop(self) -> None:
        """N4: every Clip comes off, the stop with them."""
        await self._halt()
        complete = await self._cancel_all()
        st = self._state
        if st.status not in ACTIVE_STATUSES:
            return
        self._end_stop(complete)

    async def drain_for_shutdown(self) -> None:
        """M7: the stop and targets stay on the venue while the desk is down.

        E15, EL5: a Chase entry's Clip and a Ladder entry's rungs do not.
        """
        await self._halt()
        self._stop.clear()
        p = self._state.params
        if p is None or p.entry_type not in ("chase", "ladder") or self._state.phase != "entering":
            return
        for clip in self._state.ledger.live_clips():
            if self._role(clip) != "entry":
                continue
            try:
                await self._cancel_clip(clip)
            except Exception:
                logger.exception("planner %s: entry not pulled at shutdown", self._state.algo_id)
