"""Massager job: works an open Position inside a Band. Rules in docs/massager-rules.md."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
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
    ATR_READ_TIMEOUT_S,
    ATR_RETRY_MS,
    ATR_SETTLE_MS,
    BAND_RETRY_MS,
    BAND_SETTLE_MS,
    BAND_TIMEFRAME,
    KEEP_CLOSED,
    MIN_PLACE_GAP_MS,
    MIN_REQUOTE_MS,
    OUTSIDE_GRACE_MS,
    TRIM_AFTER_MS,
    is_massager_client_order,
    next_close_ms,
)
from mayedge.algos.massager.plan import (
    ALGO_ID,
    ALGO_VERSION,
    ATR_TIMEFRAMES,
    BPS,
    KEPT_EACH_SIDE,
    RESTING_EACH_SIDE,
    Lattice,
    LevelOrder,
    MassagerParams,
    MassagerRefused,
    Side,
    Tally,
    Venue,
    basis,
    carry,
    catch_up,
    check_start,
    core,
    core_entry_after,
    fee_floor,
    judge,
    lattice,
    live_step,
    resting,
    should_redraw,
    start_anchor,
    tally_from_run,
)
from mayedge.algos.massager.state import MassagerRuntime, MassagerState
from mayedge.config import settings
from mayedge.lighter.errors import is_min_size, is_would_cross
from mayedge.numbers import check_notional, fmt_decimal, to_decimal
from mayedge.rows import is_obj, obj

logger = logging.getLogger(__name__)

ZERO = Decimal("0")

# MS21: ATR(14) of a Market on a timeframe, from closed candles. None when there is none.
AtrFn = Callable[[int, str], Awaitable[Decimal | None]]
# MS23: the last closed candle of a Market on a timeframe, as (its close time in ms, its close).
CloseFn = Callable[[int, str], Awaitable[tuple[int, Decimal] | None]]


def venue_position(payload: dict[str, Any], market_index: int) -> tuple[Decimal, Decimal | None]:
    """The Market's signed Position and the venue's entry, None without one."""
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
        if mi != market_index:
            continue
        if sign is not None and int(sign) < 0 and size > 0:
            size = -size
        entry = to_decimal(entry_raw) if entry_raw not in (None, "") else ZERO
        return size, entry if entry > 0 else None
    return ZERO, None


@dataclass(frozen=True)
class LastRun:
    """MS22: what the last Massager run on a Market left: its Tally, its own Captured,
    whether it ended with its Position closed, and its id."""

    tally: Tally
    captured: Decimal
    closed: bool
    algo_id: str


class MassagerRunner(ClipJob[ClipBookView, MassagerState]):
    """One Massager: a catch-up Clip, then two levels resting each side."""

    LABEL = "massager"

    def __init__(
        self, book: ClipBookView, atr: AtrFn | None = None, close: CloseFn | None = None
    ) -> None:
        super().__init__(book, MassagerState())
        self._atr = atr
        self._close = close
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
        return venue_position(payload, self._state.market_index)

    def _mid_now(self, market_index: int) -> Decimal | None:
        """MS10: the book's mid, None without both sides or a venue."""
        try:
            bid_s, ask_s = self._exec().best_bid_ask(market_index)
        except Exception:
            return None
        if not bid_s or not ask_s:
            return None
        return (to_decimal(bid_s) + to_decimal(ask_s)) / 2

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
            fee = qty * px * maker / BPS
            rt.book.fill(clip.side, qty, px, fee=fee)
            if rt.tally is not None:
                rt.tally.massager_fill(clip.side, qty, px, fee)
            rt.handled[clip.seq] = done + qty
            level = rt.clip_levels.get(clip.seq)
            if level is not None and rt.book.level_fill(level, qty, params.clip):
                # MS9: a whole Clip at a level makes its price the anchor.
                rt.anchor = rt.clip_marks.get(clip.seq, clip.price)
        if rt.catching:
            self._end_catch_up_when_owed_is_paid()
        self._reconcile_master()

    def _trim_ledger(self) -> None:
        """MS16: a closed Clip older than the last KEEP_CLOSED goes, with its fills, once its
        fills are counted and it has been closed TRIM_AFTER_MS. Lean, Captured and the Tally
        already hold what it did."""
        ledger = self._state.ledger
        rt = self._state.runtime
        closed = [c for c in ledger.clips if c.status != "live"]
        if len(closed) <= KEEP_CLOSED:
            return
        now = common.now_ms()
        drop = {
            c.seq
            for c in closed[:-KEEP_CLOSED]
            if c.closed_at is not None
            and now - c.closed_at >= TRIM_AFTER_MS
            and rt.handled.get(c.seq, ZERO) >= min(c.filled, c.qty)
        }
        if not drop:
            return
        self._cois -= {c.client_order_index for c in ledger.clips if c.seq in drop}
        ledger.clips = [c for c in ledger.clips if c.seq not in drop]
        ledger.fills = [f for f in ledger.fills if f.clip_seq not in drop]
        for seq in drop:
            rt.handled.pop(seq, None)
            rt.clip_levels.pop(seq, None)
            rt.clip_marks.pop(seq, None)
            rt.catch_seqs.discard(seq)
            ledger.trade_qty_by_clip.pop(seq, None)

    def _owed(self) -> Decimal:
        """MS8: the Lean the catch-up still owes, signed."""
        params = self._state.params
        rt = self._state.runtime
        if params is None:
            return ZERO
        return -rt.catch_level * params.clip - rt.book.lean

    def _end_catch_up_when_owed_is_paid(self) -> None:
        rt = self._state.runtime
        params = self._state.params
        if abs(self._owed()) < self._clip_min_qty():
            rt.catching = False
            rt.book.level = rt.catch_level
            rt.book.level_fills.clear()
            if params is not None:
                rt.anchor = start_anchor(params, rt.catch_level)

    def _on_clips_closed(self) -> None:
        self._process_fills()

    # ── outside fills ────────────────────────────────────────────────────

    async def _judge_outside(self, view: MarketView) -> bool:
        """MS11, MS12, MS15. False when the Massager paused or stopped."""
        params = self._state.params
        assert params is not None
        rt = self._state.runtime
        position, entry = self._venue_position()
        now_core = core(position, rt.book.lean)
        if rt.tally is not None and entry is not None and position == rt.tally.size:
            # MS22: keep the venue's size and entry while they agree with the Tally.
            rt.tally.venue_size = position
            rt.tally.venue_entry = entry
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
        if rt.tally is not None:
            price = mid if mid is not None else rt.tally.basis() or rt.core_entry
            rt.tally.outside(now_core - rt.core, price)
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

    async def _work_lattice(self, view: MarketView) -> None:
        """MS9, MS14: the wanted levels rest; others come off; a crossing level waits."""
        params = self._state.params
        assert params is not None
        rt = self._state.runtime
        if rt.anchor is None:
            rt.anchor = start_anchor(params, rt.book.level)
        step = rt.step if rt.step > 0 else params.step
        at, anchor = rt.book.level, rt.anchor

        def around(each_side: int) -> dict[tuple[int, str], LevelOrder]:
            orders = resting(
                params, level=at, anchor=anchor, step=step, tick=view.tick, each_side=each_side
            )
            return {(o.level, o.side): o for o in orders}

        wanted = around(RESTING_EACH_SIDE)
        # MS9: a Clip already resting a third level out stays; only the nearest two are sent.
        kept = around(KEPT_EACH_SIDE)
        live_by_key: dict[tuple[int, str], Clip] = {}
        for clip in list(self._state.ledger.live_clips()):
            level = rt.clip_levels.get(clip.seq)
            key = (level, clip.side) if level is not None and clip.side else None
            if (
                key is None
                or key not in kept
                or key in live_by_key
                or clip.price != kept[key].price  # MS21: the Step moved
            ):
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
                rt.clip_marks[placed.seq] = order.mark

    # ── the live Step ────────────────────────────────────────────────────

    async def _read_atr(self, market_index: int, timeframe: str) -> Decimal | None:
        if self._atr is None:
            return None
        try:
            atr = await asyncio.wait_for(self._atr(market_index, timeframe), ATR_READ_TIMEOUT_S)
        except Exception as e:
            logger.warning("massager ATR read failed on market %s: %s", market_index, e)
            return None
        return atr if atr is not None and atr > 0 else None

    async def _update_step(self, view: MarketView) -> None:
        """MS21: after each candle closes, read ATR; the levels follow a 20% move."""
        params = self._state.params
        rt = self._state.runtime
        if params is None or params.step_mode != "atr":
            return
        now = common.now_ms()
        if now < rt.atr_next_at:
            return
        atr = await self._read_atr(self._state.market_index, params.atr_tf)
        if atr is None:
            rt.atr_next_at = now + ATR_RETRY_MS
            return
        rt.atr = atr
        rt.atr_next_at = next_close_ms(now, params.atr_tf) + ATR_SETTLE_MS
        floor = fee_floor(params.center, self._maker_bps(), view.tick)
        live = live_step(atr, params, floor=floor)
        if should_redraw(rt.step, live):
            rt.step = live
            rt.step_moved_at = now

    # ── leaving the Band ─────────────────────────────────────────────────

    async def _read_close(self, market_index: int) -> tuple[int, Decimal] | None:
        if self._close is None:
            return None
        try:
            return await asyncio.wait_for(
                self._close(market_index, BAND_TIMEFRAME), ATR_READ_TIMEOUT_S
            )
        except Exception as e:
            logger.warning("massager close read failed on market %s: %s", market_index, e)
            return None

    async def _check_band(self) -> bool:
        """MS23: after each 1h close, a close outside the Band pauses it. False if paused."""
        params = self._state.params
        rt = self._state.runtime
        if params is None or self._close is None:
            return True
        now = common.now_ms()
        if now < rt.band_next_at:
            return True
        read = await self._read_close(self._state.market_index)
        if read is None:
            rt.band_next_at = now + BAND_RETRY_MS
            return True
        rt.band_next_at = next_close_ms(now, BAND_TIMEFRAME) + BAND_SETTLE_MS
        closed_at, close = read
        # A candle that closed before the run, or the one that paused it already, does not.
        if closed_at <= max(rt.band_close_at, self._state.created_at or 0):
            return True
        if params.band_low <= close <= params.band_high:
            return True
        rt.band_close = close
        rt.band_close_at = closed_at
        await self._pause_for("left_band")
        return False

    # ── the loop ─────────────────────────────────────────────────────────

    async def _evaluate(self) -> None:
        async with self._lock:
            if not self._ready_to_evaluate():
                return
            await self._sync_live_clips()
            self._process_fills()
            self._trim_ledger()
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
            if not await self._check_band():
                return
            await self._update_step(view)
            if self._state.runtime.catching:
                await self._work_catch_up(view)
            else:
                await self._work_lattice(view)
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

    async def start(
        self,
        *,
        algo_id: str,
        market_index: int,
        params: MassagerParams,
        last: LastRun | None = None,
        fresh: bool = False,
        chop: dict[str, Any] | None = None,
    ) -> None:
        """MS1–MS8, MS22: check, take the Core from the Position, carry the Tally, and owe
        the catch-up."""
        meta = self._exec().get_market_by_index(market_index)
        if not meta:
            raise ValueError("Unknown market")
        bid_s, ask_s = self._exec().best_bid_ask(market_index)
        if not bid_s or not ask_s:
            raise ValueError("No book to price the Band against")
        mid = (to_decimal(bid_s) + to_decimal(ask_s)) / 2
        self._state = MassagerState(market_index=market_index, symbol=meta.symbol, params=params)
        position, entry = self._venue_position()
        atr: Decimal | None = None
        if params.step_mode == "atr":
            if params.atr_tf not in ATR_TIMEFRAMES:
                raise MassagerRefused("MS3", "Pick the ATR's timeframe: 15m, 1h or 4h")
            if params.atr_mult <= 0:
                raise MassagerRefused("MS3", "Set k for the ATR Step")
            atr = await self._read_atr(market_index, params.atr_tf)
            if atr is None:
                raise MassagerRefused("MS3", "No ATR for this Market yet")
            params = replace(params, step=params.atr_mult * atr)
        venue = Venue(
            tick=Decimal(10) ** -meta.price_decimals,
            size_step=Decimal(10) ** -meta.size_decimals,
            min_qty=self._clip_min_qty(),
            maker_bps=self._maker_bps(),
        )
        params, grid = check_start(params, position=position, mid=mid, venue=venue)
        check_notional(params.swing, mid, settings.max_order_notional)
        owed = catch_up(grid, params, mid)
        now = common.now_ms()
        took = carry(
            last.tally if last else None,
            last_captured=last.captured if last else ZERO,
            last_closed=last.closed if last else False,
            source=last.algo_id if last else None,
            position=position,
            entry=entry,
            mid=mid,
            since=now,
            fresh=fresh,
        )
        runtime = MassagerRuntime(
            core_side=1 if position > 0 else -1,
            core=position,
            core_entry=entry or mid,
            catching=owed.qty > 0,
            catch_level=owed.level,
            anchor=start_anchor(params, owed.level),
            step=params.step,
            atr=atr,
            step_moved_at=now,
            atr_next_at=next_close_ms(now, params.atr_tf) + ATR_SETTLE_MS if atr else 0,
            tally=took.tally,
            carried=took.carried,
            carry_why=took.why,
            carried_from=took.source,
            band_next_at=next_close_ms(now, BAND_TIMEFRAME) + BAND_SETTLE_MS,
            chop=chop,
        )
        self._state = MassagerState(
            status=ChaseStatus.RUNNING,
            params=params,
            runtime=runtime,
            market_index=market_index,
            symbol=meta.symbol,
            remaining=params.swing,
            algo_id=algo_id,
            created_at=now,
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
        t = rt.tally
        b = t.basis() if t is not None else basis(rt.core_entry, rt.core, rt.book.captured)
        mid = self._mid_now(st.market_index)
        pnl = rt.book.marked(mid) if mid is not None else None
        band_side = None
        if rt.band_close is not None and p is not None:
            band_side = "above" if rt.band_close > p.band_high else "below"
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
            "step": fmt_decimal(rt.step if rt.step > 0 else p.step) if p else None,
            "step_mode": p.step_mode if p else None,
            "atr_mult": fmt_decimal(p.atr_mult) if p and p.step_mode == "atr" else None,
            "atr_tf": p.atr_tf if p and p.step_mode == "atr" else None,
            "atr": fmt_decimal(rt.atr) if rt.atr is not None else None,
            "step_moved_at": rt.step_moved_at or None,
            "core": fmt_decimal(rt.core),
            "lean": fmt_decimal(rt.book.lean) or "0",
            "position": fmt_decimal(position),
            "level": rt.book.level,
            "catching": rt.catching,
            "captured_pnl": fmt_decimal(rt.book.captured) or "0",
            "massager_pnl": fmt_decimal(pnl) if pnl is not None else None,
            "core_entry": fmt_decimal(t.entry if t is not None else rt.core_entry),
            "basis": fmt_decimal(b) if b is not None else None,
            "tally_captured": fmt_decimal(t.captured_before + rt.book.captured) if t else None,
            "tally_runs": t.runs if t is not None else None,
            "tally_since": t.since or None if t is not None else None,
            "carried": rt.carried,
            "carry_why": rt.carry_why,
            "carried_from": rt.carried_from,
            "band_close": fmt_decimal(rt.band_close) if rt.band_close is not None else None,
            "band_close_at": rt.band_close_at or None,
            "band_side": band_side,
            "chop": rt.chop,
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
        # MS16: a run kept before the anchor steps out from Center + level × Step.
        if runtime.step <= 0:
            runtime.step = params.step
        if runtime.anchor is None and not runtime.catching:
            runtime.anchor = start_anchor(params, runtime.book.level)
        fields = ClipState.fields_from_row(row)
        # MS16: a run kept before the Tally reads back with one built from it.
        if runtime.tally is None and runtime.core != 0:
            runtime.tally = tally_from_run(
                core_size=runtime.core,
                core_entry=runtime.core_entry,
                book=runtime.book,
                since=int(fields.get("created_at") or 0),
            )
        self._restore_state(MassagerState(params=params, runtime=runtime, **fields))
        self._reconcile_master()
