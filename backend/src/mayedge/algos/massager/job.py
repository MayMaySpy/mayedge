"""Massager job: works an open Position inside a Band. Rules in docs/massager-rules.md."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from mayedge.algos import common
from mayedge.algos.chase.iceberg import Action, MarketView
from mayedge.algos.chase.state import ChaseStatus, ClipBookView, ClipState
from mayedge.algos.clip_job import ClipJob
from mayedge.algos.common import venue_order_keys
from mayedge.algos.ledger import Clip
from mayedge.algos.massager.config import (
    ACK_WAIT_MS,
    MIN_PLACE_GAP_MS,
    MIN_REQUOTE_MS,
    OUTSIDE_GRACE_MS,
    is_massager_client_order,
)
from mayedge.algos.massager.plan import (
    ALGO_ID,
    ALGO_VERSION,
    BPS,
    Lattice,
    LevelOrder,
    MassagerParams,
    Side,
    Venue,
    basis,
    catch_up,
    check_start,
    core,
    core_entry_after,
    judge,
    lattice,
    resting,
)
from mayedge.algos.massager.state import MassagerRuntime, MassagerState
from mayedge.config import settings
from mayedge.lighter.errors import is_min_size, is_would_cross
from mayedge.numbers import check_notional, fmt_decimal, to_decimal
from mayedge.rows import is_obj, obj

logger = logging.getLogger(__name__)

ZERO = Decimal("0")


class MassagerRunner(ClipJob[ClipBookView, MassagerState]):
    """One Massager: a catch-up Clip, then two levels resting each side."""

    LABEL = "massager"

    def __init__(self, book: ClipBookView) -> None:
        super().__init__(book, MassagerState())
        self._last_catch_tx_ms = 0
        self._place_refused: str | None = None

    # ── reading the venue ────────────────────────────────────────────────

    def _orders_cancel_keys(self, orders: Any) -> set[tuple[int, int]]:
        return set(
            venue_order_keys(
                orders,
                lambda coi: is_massager_client_order(coi) and coi in self._cois,
            )
        )

    def _venue_position(self) -> tuple[Decimal, Decimal | None]:
        payload = self._exec().cached_account_payload() or {}
        for pos in payload.get("positions") or ():
            if is_obj(pos):
                mi = int(pos.get("market_index") or 0)
                size = to_decimal(pos.get("size") or "0")
                sign = pos.get("sign")
                entry_raw = pos.get("avg_entry_price") or pos.get("entry_price")
            else:
                mi = int(getattr(pos, "market_index", 0) or 0)
                size = to_decimal(getattr(pos, "size", "0") or "0")
                sign = getattr(pos, "sign", None)
                entry_raw = getattr(pos, "entry_price", None)
            if mi != self._state.market_index:
                continue
            if sign is not None and int(sign) < 0 and size > 0:
                size = -size
            entry = to_decimal(entry_raw) if entry_raw not in (None, "") else ZERO
            return size, entry if entry > 0 else None
        return ZERO, None

    def _maker_bps(self) -> Decimal:
        payload = self._exec().cached_account_payload() or {}
        return to_decimal(payload.get("maker_fee_bps") or "0")

    def _grid(self, view: MarketView) -> Lattice | None:
        params = self._state.params
        return lattice(params, view.tick) if params else None

    # ── what it has done ─────────────────────────────────────────────────

    def _reconcile_master(self) -> None:
        """Heal clip fills from the tape; filled is the Lean, remaining the room to the Swing."""
        ledger = self._state.ledger
        by_seq: dict[int, Decimal] = {}
        for f in ledger.fills:
            by_seq[f.clip_seq] = by_seq.get(f.clip_seq, ZERO) + f.qty
        for c in ledger.clips:
            taped = by_seq.get(c.seq, ZERO)
            if taped > c.filled:
                c.filled = min(c.qty, taped)
        lean = abs(self._state.runtime.book.lean)
        swing = self._state.params.swing if self._state.params else ZERO
        self._state.filled = lean
        self._state.remaining = max(ZERO, swing - lean)

    def _avg_fill_price(self, clip: Clip) -> Decimal:
        fills = [f for f in self._state.ledger.fills if f.clip_seq == clip.seq]
        qty = sum((f.qty for f in fills), ZERO)
        if qty > 0:
            return sum((f.price * f.qty for f in fills), ZERO) / qty
        return clip.price

    def _process_fills(self) -> None:
        """MS9, MS10: credit each Clip's new fills to the Lean and to its level."""
        params = self._state.params
        if params is None:
            return
        rt = self._state.runtime
        maker = self._maker_bps()
        for clip in self._state.ledger.clips:
            if clip.side is None:
                continue
            done = rt.handled.get(clip.seq, ZERO)
            qty = min(clip.filled, clip.qty) - done
            if qty <= 0:
                continue
            px = self._avg_fill_price(clip)
            rt.book.fill(clip.side, qty, px, fee=qty * px * maker / BPS)
            rt.handled[clip.seq] = done + qty
            level = rt.clip_levels.get(clip.seq)
            if level is not None:
                rt.book.level_fill(level, qty, params.clip)
        if rt.catching:
            self._end_catch_up_when_owed_is_paid()
        self._reconcile_master()

    def _owed(self) -> Decimal:
        """MS8: the Lean the catch-up still owes, signed."""
        params = self._state.params
        rt = self._state.runtime
        if params is None:
            return ZERO
        return -rt.catch_level * params.clip - rt.book.lean

    def _end_catch_up_when_owed_is_paid(self) -> None:
        rt = self._state.runtime
        if abs(self._owed()) < self._clip_min_qty():
            rt.catching = False
            rt.book.level = rt.catch_level
            rt.book.level_fills.clear()

    def _on_clips_closed(self) -> None:
        self._process_fills()

    # ── outside fills ────────────────────────────────────────────────────

    async def _judge_outside(self, view: MarketView) -> bool:
        """MS11, MS12, MS15. False when the Massager paused or stopped."""
        params = self._state.params
        assert params is not None
        rt = self._state.runtime
        position, _ = self._venue_position()
        now_core = core(position, rt.book.lean)
        if now_core == rt.core:
            rt.pending_core = None
            return True
        now = common.now_ms()
        if rt.pending_core != now_core:
            rt.pending_core = now_core
            rt.pending_since = now
            return True
        if now - rt.pending_since < OUTSIDE_GRACE_MS:
            return True
        mid = (view.bid + view.ask) / 2 if view.bid and view.ask else None
        if mid is not None:
            rt.core_entry = core_entry_after(rt.core_entry, rt.core, now_core - rt.core, mid)
        rt.core = now_core
        rt.pending_core = None
        verdict = judge(position, rt.book.lean, core_side=rt.core_side, swing=params.swing)
        if verdict == "stop":
            await self._end("position_closed")
            return False
        if verdict == "pause":
            await self._pause_for("core_within_swing")
            return False
        return True

    async def _pause_for(self, reason: str) -> None:
        if await self._cancel_algo_orders():
            self._state.status = ChaseStatus.PAUSED
            self._hold(reason)
        else:
            self._state.status = ChaseStatus.ERROR
            self._state.error = f"{reason}: cancel incomplete"
        self._publish()

    async def _end(self, reason: str) -> None:
        complete = await self._cancel_algo_orders()
        self._hold(reason)
        if not complete:
            self._state.status = ChaseStatus.ERROR
            self._state.error = f"{reason}: cancel incomplete"
            self._publish()
            return
        self._state.status = ChaseStatus.STOPPED
        self._finish()
        self._stop.set()

    # ── placing ──────────────────────────────────────────────────────────

    async def _place(self, side: Side, price: Decimal, qty: Decimal) -> Clip | None:
        """MS17: every Clip is a post-only Limit, never reduce-only."""
        coi = self._next_coi()
        try:
            await self._exec().create_limit_order(
                market_index=self._state.market_index,
                side=side,
                size=fmt_decimal(qty) or "0",
                price=fmt_decimal(price) or "0",
                time_in_force="post_only",
                reduce_only=False,
                client_order_index=coi,
            )
        except Exception as e:
            if is_min_size(e):
                self._place_refused = "below_min_qty"
                return None
            if is_would_cross(e):
                self._place_refused = "would_cross"
                return None
            if self._handle_tx_err(e):
                return None
            raise
        self._last_tx_ms = common.now_ms()
        found = self._find_open(coi)
        idx = int(found["order_index"]) if found and found.get("order_index") else None
        return self._state.ledger.place(
            client_order_index=coi,
            price=price,
            qty=qty,
            now=common.now_ms(),
            order_index=idx,
            side=side,
        )

    def _gap_open(self) -> bool:
        now = common.now_ms()
        if now < self._backoff_until:
            return False
        return not (self._last_tx_ms > 0 and now - self._last_tx_ms < MIN_PLACE_GAP_MS)

    async def _work_catch_up(self, view: MarketView) -> None:
        """MS13: one post-only Clip at the touch until the Lean the start owed is paid."""
        rt = self._state.runtime
        owed = self._owed()
        side: Side = "buy" if owed > 0 else "sell"
        touch = view.bid if side == "buy" else view.ask
        live = [c for c in self._state.ledger.live_clips() if c.seq in rt.catch_seqs]
        for clip in live[1:]:
            await self._cancel_clip(clip)
        clip = live[0] if live else None
        if touch is None:
            return
        if clip is not None:
            if clip.price == touch:
                return
            waiting_ack = not clip.seen_on_book and common.now_ms() - clip.placed_at < ACK_WAIT_MS
            cooling = common.now_ms() - self._last_catch_tx_ms < MIN_REQUOTE_MS
            if waiting_ack or cooling:
                return
            await self._cancel_clip(clip)
            self._last_catch_tx_ms = common.now_ms()
            return
        qty = abs(self._owed())
        if qty < self._clip_min_qty() or not self._gap_open():
            return
        placed = await self._place(side, touch, qty)
        if placed is not None:
            rt.catch_seqs.add(placed.seq)
            self._last_catch_tx_ms = common.now_ms()

    def _would_cross(self, order: LevelOrder, view: MarketView) -> bool:
        return self._working_crosses(order.price, view, order.side)

    async def _work_lattice(self, view: MarketView, grid: Lattice) -> None:
        """MS9, MS14: the wanted levels rest; others come off; a crossing level waits."""
        params = self._state.params
        assert params is not None
        rt = self._state.runtime
        wanted = {(o.level, o.side): o for o in resting(grid, params, rt.book.level)}
        live_by_key: dict[tuple[int, str], Clip] = {}
        for clip in list(self._state.ledger.live_clips()):
            level = rt.clip_levels.get(clip.seq)
            key = (level, clip.side) if level is not None and clip.side else None
            if key is None or key not in wanted or key in live_by_key:
                await self._cancel_clip(clip)
                continue
            if self._working_crosses(clip.price, view, clip.side or "buy"):
                await self._cancel_clip(clip)
                continue
            live_by_key[(key[0], key[1])] = clip
        self._place_refused = None
        for key, order in wanted.items():
            if key in live_by_key:
                continue
            if self._would_cross(order, view):
                continue
            qty = rt.book.qty_for(order, params.swing)
            if qty < self._clip_min_qty():
                continue
            if not self._gap_open():
                break
            placed = await self._place(order.side, order.price, qty)
            if placed is not None:
                rt.clip_levels[placed.seq] = order.level

    # ── the loop ─────────────────────────────────────────────────────────

    async def _evaluate(self) -> None:
        async with self._lock:
            if not self._ready_to_evaluate():
                return
            await self._sync_live_clips()
            self._process_fills()
            if common.now_ms() < self._backoff_until:
                self._hold_quotes(self._backoff_reason or "rate_limited")
                return
            if not self._exec().is_book_synced(self._state.market_index):
                self._hold_quotes("book_unsynced")
                return
            if not self._account_ready():
                self._hold_quotes("account_unsynced")
                return
            view = self._market_view()
            grid = self._grid(view) if view else None
            if view is None or grid is None:
                self._hold_quotes("no_market")
                return
            if not await self._judge_outside(view):
                return
            if self._state.runtime.catching:
                await self._work_catch_up(view)
            else:
                await self._work_lattice(view, grid)
            self._process_fills()
            live = self._state.ledger.live_clips()
            self._state.quote_action = Action.REST.value if live else Action.PAUSE.value
            if live:
                self._state.reason = "catch_up" if self._state.runtime.catching else None
            else:
                self._state.reason = self._place_refused or "waiting"
            self._sync_rest_from_live()
            self._publish()

    def _sync_rest_from_live(self) -> None:
        live = self._state.ledger.live_clips()
        self._state.rest_price = live[-1].price if live else None
        self._state.rest_qty = sum((c.remaining for c in live), ZERO) if live else None

    # ── start, snapshot, restore ─────────────────────────────────────────

    async def start(self, *, algo_id: str, market_index: int, params: MassagerParams) -> None:
        """MS1–MS8: check, take the Core from the Position, and owe the catch-up."""
        meta = self._exec().get_market_by_index(market_index)
        if not meta:
            raise ValueError("Unknown market")
        bid_s, ask_s = self._exec().best_bid_ask(market_index)
        if not bid_s or not ask_s:
            raise ValueError("No book to price the Band against")
        mid = (to_decimal(bid_s) + to_decimal(ask_s)) / 2
        self._state = MassagerState(market_index=market_index, symbol=meta.symbol, params=params)
        position, entry = self._venue_position()
        venue = Venue(
            tick=Decimal(10) ** -meta.price_decimals,
            size_step=Decimal(10) ** -meta.size_decimals,
            min_qty=self._clip_min_qty(),
            maker_bps=self._maker_bps(),
        )
        params, grid = check_start(params, position=position, mid=mid, venue=venue)
        check_notional(params.swing, mid, settings.max_order_notional)
        owed = catch_up(grid, params, mid)
        runtime = MassagerRuntime(
            core_side=1 if position > 0 else -1,
            core=position,
            core_entry=entry or mid,
            catching=owed.qty > 0,
            catch_level=owed.level,
        )
        self._state = MassagerState(
            status=ChaseStatus.RUNNING,
            params=params,
            runtime=runtime,
            market_index=market_index,
            symbol=meta.symbol,
            remaining=params.swing,
            algo_id=algo_id,
            created_at=common.now_ms(),
        )
        self._cois.clear()
        self._reset_job()
        await self._begin()

    def snapshot(self, s: MassagerState | None = None) -> dict[str, Any]:
        st = s if s is not None else self._state
        self._reconcile_master()
        p = st.params
        rt = st.runtime
        position = rt.core + rt.book.lean
        payload = p.to_json() if p else {}
        payload["runtime"] = rt.to_json()
        kinds = {seq: f"level {lv}" for seq, lv in rt.clip_levels.items()}
        kinds.update({seq: "catch_up" for seq in rt.catch_seqs})
        ledger = st.ledger.to_dict()
        ledger["clips"] = [
            {**c, "kind": kinds.get(int(c["seq"]))} if is_obj(c) else c
            for c in ledger.get("clips") or ()
        ]
        b = basis(rt.core_entry, rt.core, rt.book.captured)
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
            "side": None,
            "qty": fmt_decimal(p.swing) if p else None,
            "display_qty": fmt_decimal(p.clip) if p else None,
            "offset_bps": None,
            "price_floor": fmt_decimal(p.band_low) if p else None,
            "price_ceiling": fmt_decimal(p.band_high) if p else None,
            "step": fmt_decimal(p.step) if p else None,
            "core": fmt_decimal(rt.core),
            "lean": fmt_decimal(rt.book.lean) or "0",
            "position": fmt_decimal(position),
            "level": rt.book.level,
            "catching": rt.catching,
            "captured_pnl": fmt_decimal(rt.book.captured) or "0",
            "core_entry": fmt_decimal(rt.core_entry),
            "basis": fmt_decimal(b) if b is not None else None,
            "remaining": fmt_decimal(st.remaining),
            "filled": fmt_decimal(st.filled),
            "quote_action": st.quote_action,
            "reason": st.reason,
            "rest_price": fmt_decimal(st.rest_price),
            "rest_qty": fmt_decimal(st.rest_qty),
            "working_coi": None,
            "error": st.error,
            "created_at": st.created_at or None,
            "params_json": payload,
            **ledger,
        }

    def hydrate_from_row(self, row: dict[str, Any]) -> None:
        """MS16: Lean, level, Captured, Core and the catch-up come back with the run."""
        raw = obj(row.get("params_json"))
        params = MassagerParams.from_json(raw)
        runtime = MassagerRuntime.from_json(obj(raw.get("runtime")))
        fields = ClipState.fields_from_row(row)
        self._restore_state(MassagerState(params=params, runtime=runtime, **fields))
        self._reconcile_master()
