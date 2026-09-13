from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import replace
from decimal import Decimal
from typing import Any

from mayedge.algos.chase.config import STOP_CANCEL_GAP_S, STOP_CANCEL_TRIES
from mayedge.algos.chase.execution import ChaseExecution
from mayedge.algos.chase.fills import may_invent_fill
from mayedge.algos.chase.iceberg import Action, MarketView, leftover_is_dust
from mayedge.algos.chase.place import ChasePlaceMixin
from mayedge.algos.chase.state import ACTIVE_STATUSES, ChaseStatus
from mayedge.algos.chase.util import (
    _dec,
    _fmt,
    _is_invalid_nonce,
    _is_min_size,
    _is_order_not_found,
    _is_rate_limit,
    _is_would_cross,
)
from mayedge.algos.grid import util as grid_util
from mayedge.algos.grid.config import (
    ACK_WAIT_MS,
    GRID_COI_BASE,
    GRID_COI_END,
    MIN_PLACE_GAP_MS,
    MIN_REQUOTE_MS,
)
from mayedge.algos.grid.config import (
    AUTO_RESUME_ERRORS as GRID_AUTO_RESUME,
)
from mayedge.algos.grid.decide import (
    ALGO_ID,
    ALGO_VERSION,
    GridAction,
    GridParams,
    GridPlan,
    GridRuntime,
    SideQuote,
    TpTarget,
    align_runtime_to_position,
    credit_grid_fill,
    decide,
)
from mayedge.algos.grid.state import GridBookView, GridState
from mayedge.algos.ledger import Clip
from mayedge.config import settings
from mayedge.numbers import check_notional

logger = logging.getLogger(__name__)


class GridRunner(ChasePlaceMixin[GridBookView, GridState]):
    """Two-sided chase-grid job."""

    def __init__(self, book: GridBookView) -> None:
        self._book = book
        self._state = GridState()
        self._cois: set[int] = set()
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._lock = asyncio.Lock()
        self._canceling = False
        self._last_tx_ms = 0
        self._last_chase_tx_ms = 0
        self._backoff_until = 0
        self._backoff_reason: str | None = None
        self._pending_trades: list[dict[str, Any]] = []
        self._missing_refreshed: set[int] = set()
        self._unproven_retry_at = 0
        self._handled_clip_seqs: set[int] = set()

    @property
    def state(self) -> GridState:
        return self._state

    def _orders_cancel_keys(self, orders: Any) -> set[tuple[int, int]]:
        return set(grid_util._grid_order_keys(orders, self._cois))

    def _reconcile_master(self) -> None:
        inv = abs(self._state.runtime.inventory)
        self._state.filled = inv
        if self._state.params:
            self._state.remaining = max(Decimal("0"), self._state.params.max_inventory - inv)
        else:
            self._state.remaining = Decimal("0")

    def _clip_kind(self, clip: Clip) -> str | None:
        return self._state.runtime.clip_kinds.get(clip.seq)

    def _note_tx(self, kind: str | None = None) -> None:
        now = grid_util.now_ms()
        self._last_tx_ms = now
        if kind in ("chase_buy", "chase_sell"):
            self._last_chase_tx_ms = now

    def _lot_for_clip(self, clip: Clip):
        for lot in self._state.runtime.lots:
            if lot.tp_clip_seq == clip.seq:
                return lot
        return None

    def _avg_fill_price(self, clip: Clip) -> Decimal:
        prices = [f.price for f in self._state.ledger.fills if f.clip_seq == clip.seq]
        if prices:
            return sum(prices, Decimal("0")) / Decimal(len(prices))
        return clip.price

    def _process_new_fills(self) -> None:
        params = self._state.params
        if not params:
            return
        view = self._market_view()
        if not view:
            return
        now = grid_util.now_ms()
        rt = self._state.runtime
        for clip in self._state.ledger.clips:
            if clip.side is None:
                continue
            handled = rt.handled_fill_qty.get(clip.seq, Decimal("0"))
            qty = min(clip.filled, clip.qty) - handled
            if qty <= 0:
                continue
            px = self._avg_fill_price(clip)
            credit_grid_fill(
                rt,
                kind=self._clip_kind(clip),
                side=clip.side,
                qty=qty,
                fill_vwap=px,
                params=params,
                market=view,
                now=now,
                lot=self._lot_for_clip(clip),
            )
            rt.handled_fill_qty[clip.seq] = handled + qty
            self._handled_clip_seqs.add(clip.seq)

    async def _sync_fills(self) -> None:
        self._drain_trades()
        live = self._state.ledger.live_clips()
        if not live:
            self._reconcile_master()
            self._process_new_fills()
            return
        for clip in list(live):
            await self._sync_one_clip(clip)
        self._reconcile_master()
        self._process_new_fills()

    async def _sync_one_clip(self, clip: Clip) -> None:
        from mayedge.algos.chase import util as chase_util
        from mayedge.algos.chase.config import STALE_ACK_MS

        found = self._find_open(clip.client_order_index)
        now = chase_util.now_ms()
        if found is None:
            if self._canceling:
                self._state.ledger.close_missing(clip, canceling=True, now=now)
                return
            if not clip.seen_on_book:
                if now - clip.placed_at < STALE_ACK_MS:
                    return
                if getattr(self, "_backoff_until", 0) > now:
                    return
                await self._resolve_vanished_clip(clip, now=now)
                return
            if self._may_invent_fill(clip, now):
                self._close_missing_clip(clip, now=now, assume_fill=True)
                return
            if clip.missing_since is None:
                clip.missing_since = now
                return
            if now - clip.missing_since < self._book.missing_fill_grace_ms:
                return
            if getattr(self, "_backoff_until", 0) > now:
                return
            if clip.seq not in self._missing_refreshed:
                self._missing_refreshed.add(clip.seq)
            await self._resolve_vanished_clip(clip, now=now)
            return
        rem = _dec(found.get("remaining") or "0")
        filled = _dec(found.get("filled") or "0")
        idx = int(found.get("order_index") or 0) or None
        self._state.ledger.apply_open(
            clip, rem, now=now, order_index=idx, book_filled=filled if filled > 0 else None
        )

    def _chase_clip(self, side: str):
        want = "chase_buy" if side == "buy" else "chase_sell"
        for clip in reversed(self._state.ledger.clips):
            if clip.status != "live" or clip.side != side:
                continue
            if self._lot_for_clip(clip) is not None:
                continue
            kind = self._clip_kind(clip)
            if kind == "tp":
                continue
            if kind == want or kind is None:
                return clip
        return None

    def _sync_rest_from_live(self) -> None:
        live_bid = self._chase_clip("buy")
        live_ask = self._chase_clip("sell")
        if live_bid and live_ask:
            self._state.rest_price = (live_bid.price + live_ask.price) / 2
            self._state.rest_qty = live_bid.remaining + live_ask.remaining
        elif live_bid:
            self._state.rest_price = live_bid.price
            self._state.rest_qty = live_bid.remaining
        elif live_ask:
            self._state.rest_price = live_ask.price
            self._state.rest_qty = live_ask.remaining
        else:
            self._state.rest_price = None
            self._state.rest_qty = None

    def snapshot(self, s: GridState | None = None) -> dict[str, Any]:
        st = s or self._state
        self._reconcile_master()
        p = st.params
        payload = p.to_json() if p else {}
        payload["runtime"] = st.runtime.to_json()
        ledger = st.ledger.to_dict()
        kinds = st.runtime.clip_kinds
        clips = []
        for clip in ledger.get("clips") or []:
            if isinstance(clip, dict):
                seq = clip.get("seq")
                kind = kinds.get(int(seq)) if seq is not None else None
                clips.append({**clip, "kind": kind})
            else:
                clips.append(clip)
        ledger["clips"] = clips
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
            "qty": _fmt(p.max_inventory) if p else None,
            "display_qty": _fmt(p.display_qty) if p else None,
            "offset_bps": _fmt(p.offset_bps) if p else None,
            "price_floor": _fmt(p.price_floor) if p else None,
            "price_ceiling": _fmt(p.price_ceiling) if p else None,
            "profit_bps": _fmt(p.profit_bps) if p else None,
            "grid_bps": _fmt(p.grid_bps) if p else None,
            "be_delay_ms": p.be_delay_ms if p else 0,
            "be_bps": _fmt(p.be_bps) if p else None,
            "inventory": _fmt(st.runtime.inventory),
            "inventory_vwap": _fmt(st.runtime.inventory_vwap),
            "captured_pnl": _fmt(st.runtime.captured_pnl) or "0",
            "remaining": _fmt(st.remaining),
            "filled": _fmt(st.filled),
            "quote_action": st.quote_action,
            "reason": st.reason,
            "rest_price": _fmt(st.rest_price),
            "rest_qty": _fmt(st.rest_qty),
            "working_coi": None,
            "error": st.error,
            "created_at": st.created_at or None,
            "params_json": payload,
            "lots": [lot.to_json() for lot in st.runtime.lots],
            "merged_active": st.runtime.merged_active,
            **ledger,
            "working_bid": (cb.to_dict() if (cb := self._chase_clip("buy")) else None),
            "working_ask": (cs.to_dict() if (cs := self._chase_clip("sell")) else None),
        }

    def _publish(self) -> None:
        self._book.publish()

    def _finish(self) -> None:
        self._book.finish(self)

    def _live_fee_bps(self) -> tuple[Decimal, Decimal]:
        payload = self._exec().cached_account_payload() or {}
        maker = _dec(payload.get("maker_fee_bps") or "0")
        taker = _dec(payload.get("taker_fee_bps") or "0")
        return maker, taker

    def _apply_live_fees(self) -> None:
        params = self._state.params
        if params is None:
            return
        maker, taker = self._live_fee_bps()
        be_bps = maker + taker
        if params.be_bps != be_bps:
            self._state.params = replace(params, be_bps=be_bps)

    def _next_coi(self) -> int:
        coi = self._book.alloc_coi()
        self._cois.add(coi)
        return coi

    def _exec(self) -> ChaseExecution:
        return self._book.execution()

    def _seed_inventory(self) -> None:
        payload = self._exec().cached_account_payload() or {}
        for pos in payload.get("positions") or []:
            if int(pos.get("market_index") or 0) != self._state.market_index:
                continue
            size = _dec(pos.get("size") or "0")
            if size == 0:
                return
            entry = _dec(pos.get("avg_entry_price") or pos.get("entry_price") or "0")
            self._state.runtime.inventory = size
            self._state.runtime.inventory_vwap = entry if entry > 0 else None
            self._state.runtime.grid_anchor = entry if entry > 0 else None
            return

    def _venue_position(self) -> tuple[Decimal, Decimal | None]:
        payload = self._exec().cached_account_payload() or {}
        for pos in payload.get("positions") or []:
            if isinstance(pos, dict):
                mi = int(pos.get("market_index") or 0)
                size = _dec(pos.get("size") or "0")
                entry_raw = pos.get("avg_entry_price") or pos.get("entry_price")
            else:
                mi = int(getattr(pos, "market_index", 0) or 0)
                size = _dec(getattr(pos, "size", "0") or "0")
                entry_raw = getattr(pos, "entry_price", None)
            if mi != self._state.market_index:
                continue
            entry = _dec(entry_raw) if entry_raw not in (None, "") else Decimal("0")
            return size, entry if entry > 0 else None
        return Decimal("0"), None

    def _align_runtime_to_venue(self, view: MarketView) -> None:
        params = self._state.params
        if params is None:
            return
        size, entry = self._venue_position()
        align_runtime_to_position(
            self._state.runtime,
            venue_size=size,
            entry=entry,
            params=params,
            market=view,
            now=grid_util.now_ms(),
        )

    async def _place_side(
        self,
        side: str,
        quote: SideQuote,
        *,
        kind: str,
        reduce_only: bool = False,
    ) -> Clip | None:
        if quote.action != GridAction.REST or quote.price is None or quote.qty is None:
            return None
        coi = self._next_coi()
        try:
            await self._exec().create_limit_order(
                market_index=self._state.market_index,
                side=side,
                size=_fmt(quote.qty) or "0",
                price=_fmt(quote.price) or "0",
                time_in_force="post_only",
                reduce_only=reduce_only,
                client_order_index=coi,
            )
        except ValueError as e:
            if _is_min_size(e) or _is_would_cross(e):
                return None
            if self._handle_tx_err(e):
                return None
            raise
        except Exception as e:
            if _is_min_size(e) or _is_would_cross(e):
                return None
            if self._handle_tx_err(e):
                return None
            raise
        self._note_tx(kind)
        found = self._find_open(coi)
        idx = int(found["order_index"]) if found and found.get("order_index") else None
        clip = self._state.ledger.place(
            client_order_index=coi,
            price=quote.price,
            qty=quote.qty,
            now=grid_util.now_ms(),
            order_index=idx,
            side=side,  # type: ignore[arg-type]
        )
        self._state.runtime.clip_kinds[clip.seq] = kind
        return clip

    async def _modify_side(self, clip: Clip, quote: SideQuote) -> None:
        if quote.price is None:
            return
        idx = self._modify_index(clip)
        if idx is None:
            self._state.ledger.close_missing(clip, canceling=True, now=grid_util.now_ms())
            return
        rem = clip.remaining if clip.remaining > 0 else (quote.qty or clip.qty)
        if leftover_is_dust(rem, self._clip_min_qty()):
            await self._cancel_clip(clip)
            return
        try:
            await self._exec().modify_order(
                market_index=self._state.market_index,
                order_index=idx,
                price=_fmt(quote.price) or "0",
                size=_fmt(rem) or "0",
            )
        except Exception as e:
            if _is_would_cross(e):
                return
            if _is_min_size(e):
                await self._cancel_clip(clip)
                return
            if self._handle_tx_err(e):
                return
            logger.warning("grid modify failed: %s", e)
            return
        self._note_tx(self._clip_kind(clip))
        self._state.ledger.amend(clip, price=quote.price, now=grid_util.now_ms())

    async def _cancel_clip(self, clip: Clip) -> None:
        await self._sync_fills()
        if clip.status != "live":
            return
        if not self._exec().enabled:
            self._state.ledger.close_missing(clip, canceling=True, now=grid_util.now_ms())
            self._process_new_fills()
            self._reconcile_master()
            return
        coi = clip.client_order_index
        for attempt in range(STOP_CANCEL_TRIES):
            target = self._cancel_target(clip)
            if target is None:
                if await self._coi_open_on_venue(coi):
                    return
                now = grid_util.now_ms()
                if may_invent_fill(
                    clip,
                    now,
                    ledger=self._state.ledger,
                    orders_hydrated=self._exec().orders_hydrated(),
                    grace_ms=self._book.missing_fill_grace_ms,
                ):
                    self._close_missing_clip(clip, now=now, assume_fill=True)
                else:
                    self._state.ledger.close_missing(clip, canceling=True, now=now)
                self._process_new_fills()
                self._reconcile_master()
                return
            mi, oid = target
            self._canceling = True
            try:
                try:
                    await self._exec().cancel_order(mi, oid)
                    self._last_tx_ms = grid_util.now_ms()
                except Exception as e:
                    if _is_order_not_found(e) or _is_min_size(e):
                        pass
                    elif self._handle_tx_err(e):
                        return
                    else:
                        raise
            finally:
                self._canceling = False
            if not await self._coi_open_on_venue(coi):
                now = grid_util.now_ms()
                if may_invent_fill(
                    clip,
                    now,
                    ledger=self._state.ledger,
                    orders_hydrated=self._exec().orders_hydrated(),
                    grace_ms=self._book.missing_fill_grace_ms,
                ):
                    self._close_missing_clip(clip, now=now, assume_fill=True)
                else:
                    self._state.ledger.close_missing(clip, canceling=True, now=now)
                self._process_new_fills()
                self._reconcile_master()
                return
            if attempt + 1 < STOP_CANCEL_TRIES:
                await asyncio.sleep(STOP_CANCEL_GAP_S)

    def _keep_child_cois(self, plan: GridPlan) -> set[int]:
        keep: set[int] = set()
        if plan.buy is not None and plan.buy.action == GridAction.REST:
            clip = self._chase_clip("buy")
            if clip:
                keep.add(clip.client_order_index)
        if plan.sell is not None and plan.sell.action == GridAction.REST:
            clip = self._chase_clip("sell")
            if clip:
                keep.add(clip.client_order_index)
        wanted = {t.lot_id for t in plan.tps}
        for lot in self._state.runtime.lots:
            if lot.lot_id not in wanted or lot.tp_clip_seq is None:
                continue
            clip = next(
                (
                    c
                    for c in self._state.ledger.clips
                    if c.seq == lot.tp_clip_seq and c.status == "live"
                ),
                None,
            )
            if clip:
                keep.add(clip.client_order_index)
        return keep

    async def _sweep_dead_children(self, keep_cois: set[int]) -> None:
        """Pull chase/TP children that the ledger dropped or no longer wants."""
        for clip in list(self._state.ledger.live_clips()):
            if clip.client_order_index in keep_cois:
                continue
            await self._cancel_clip(clip)
            if grid_util.now_ms() < self._backoff_until:
                return
        payload = self._exec().cached_account_payload() or {}
        for raw in payload.get("open_orders") or []:
            if not isinstance(raw, dict):
                coi = int(getattr(raw, "client_order_index", 0) or 0)
                mi = int(getattr(raw, "market_index", 0) or self._state.market_index)
                oid = int(getattr(raw, "order_index", 0) or 0) or coi
            else:
                coi = int(raw.get("client_order_index") or 0)
                mi = int(raw.get("market_index") or self._state.market_index)
                oid = int(raw.get("order_index") or 0) or coi
            if mi != self._state.market_index:
                continue
            if not (GRID_COI_BASE <= coi < GRID_COI_END):
                continue
            if coi in keep_cois:
                continue
            try:
                await self._exec().cancel_order(mi, oid)
                self._last_tx_ms = grid_util.now_ms()
            except Exception as e:
                if _is_order_not_found(e) or _is_min_size(e):
                    continue
                if self._handle_tx_err(e):
                    return
                logger.warning("grid sweep cancel failed: %s", e)
                return

    async def _ensure_tp(self, target: TpTarget) -> None:
        lot = next(
            (item for item in self._state.runtime.lots if item.lot_id == target.lot_id), None
        )
        if not lot or lot.qty <= 0:
            return
        live = None
        if lot.tp_clip_seq is not None:
            live = next(
                (
                    c
                    for c in self._state.ledger.clips
                    if c.seq == lot.tp_clip_seq and c.status == "live"
                ),
                None,
            )
        if live is None:
            quote = SideQuote(GridAction.REST, price=target.price, qty=target.qty)
            clip = await self._place_side(target.side, quote, kind="tp", reduce_only=True)
            if clip:
                lot.tp_clip_seq = clip.seq
            return
        if self._clip_is_dust(live):
            await self._cancel_clip(live)
            if leftover_is_dust(target.qty, self._clip_min_qty()):
                return
            clip = await self._place_side(
                target.side,
                SideQuote(GridAction.REST, price=target.price, qty=target.qty),
                kind="tp",
                reduce_only=True,
            )
            if clip:
                lot.tp_clip_seq = clip.seq
            return
        if live.price != target.price or live.qty != target.qty:
            await self._modify_side(
                live, SideQuote(GridAction.REST, price=target.price, qty=target.qty)
            )

    async def _execute_be(self, side: str, qty: Decimal) -> None:
        coi = self._next_coi()
        await self._exec().create_market_order(
            self._state.market_index,
            side,
            _fmt(qty) or "0",
            0.01,
            reduce_only=True,
            client_order_index=coi,
        )
        self._last_tx_ms = grid_util.now_ms()
        now = grid_util.now_ms()
        rt = self._state.runtime
        rt.merged_active = False
        rt.lots = [lot for lot in rt.lots if not lot.merged]
        rt.reentry_until = now + (
            self._state.params.post_be_cooldown_ms if self._state.params else 60_000
        )
        self._reconcile_master()

    async def _manage_side(
        self,
        side: str,
        quote: SideQuote | None,
        *,
        kind: str,
        view: MarketView,
        cooling: bool,
    ) -> None:
        live = self._chase_clip(side)
        if quote is None or quote.action != GridAction.REST or quote.price is None:
            if live:
                await self._cancel_clip(live)
            return
        if live is None:
            await self._place_side(side, quote, kind=kind)
            return
        if self._clip_is_dust(live):
            await self._cancel_clip(live)
            if self._chase_clip(side) is None:
                await self._place_side(side, quote, kind=kind)
            return
        if live.price == quote.price:
            return
        waiting_ack = not live.seen_on_book and grid_util.now_ms() - live.placed_at < ACK_WAIT_MS
        if waiting_ack:
            return
        if cooling:
            return
        if self._working_crosses(live.price, view, side):
            await self._cancel_clip(live)
            return
        await self._modify_side(live, quote)

    async def _evaluate(self) -> None:
        async with self._lock:
            if (
                self._stop.is_set()
                or self._state.status != ChaseStatus.RUNNING
                or not self._state.params
            ):
                return
            if not self._exec().enabled:
                self._state.status = ChaseStatus.ERROR
                self._state.error = "Trading not configured"
                self._publish()
                return

            await self._sync_fills()
            now = grid_util.now_ms()
            if now < self._backoff_until:
                self._state.quote_action = Action.PAUSE.value
                self._state.reason = self._backoff_reason or "rate_limited"
                self._sync_rest_from_live()
                self._publish()
                return

            if not self._exec().is_book_synced(self._state.market_index):
                self._state.quote_action = Action.PAUSE.value
                self._state.reason = "book_unsynced"
                self._sync_rest_from_live()
                self._publish()
                return

            if not self._account_ready():
                self._state.quote_action = Action.PAUSE.value
                self._state.reason = "account_unsynced"
                self._sync_rest_from_live()
                self._publish()
                return

            view = self._market_view()
            if view is None:
                self._state.quote_action = Action.PAUSE.value
                self._state.reason = "no_market"
                self._publish()
                return

            self._apply_live_fees()
            params = self._state.params
            if params is None:
                return
            self._align_runtime_to_venue(view)
            plan = decide(params, view, self._state.runtime, now=now)
            self._state.quote_action = plan.quote_action
            self._state.reason = plan.reason

            await self._sweep_dead_children(self._keep_child_cois(plan))
            if grid_util.now_ms() < self._backoff_until:
                self._sync_rest_from_live()
                self._publish()
                return

            if plan.be is not None and plan.be.qty > 0:
                await self._execute_be(plan.be.side, plan.be.qty)
                self._sync_rest_from_live()
                self._publish()
                return

            cooling = self._last_chase_tx_ms > 0 and now - self._last_chase_tx_ms < MIN_REQUOTE_MS
            await self._manage_side("buy", plan.buy, kind="chase_buy", view=view, cooling=cooling)
            await self._manage_side(
                "sell", plan.sell, kind="chase_sell", view=view, cooling=cooling
            )

            for target in plan.tps:
                if (
                    self._last_tx_ms > 0
                    and grid_util.now_ms() - self._last_tx_ms < MIN_PLACE_GAP_MS
                ):
                    break
                await self._ensure_tp(target)

            self._sync_rest_from_live()
            self._publish()

    def hydrate_from_row(self, row: dict[str, Any]) -> None:
        raw = row.get("params_json") or {}
        if not isinstance(raw, dict):
            raw = {}
        runtime_raw = raw.get("runtime") or {}
        params = GridParams.from_json(
            {
                "max_inventory": row.get("qty") or raw.get("max_inventory") or "0",
                "display_qty": row.get("display_qty") or raw.get("display_qty") or "0",
                "offset_bps": row.get("offset_bps") or raw.get("offset_bps") or "4",
                "profit_bps": row.get("profit_bps") or raw.get("profit_bps") or "0",
                "grid_bps": row.get("grid_bps")
                or raw.get("grid_bps")
                or row.get("profit_bps")
                or "0",
                "price_floor": row.get("price_floor") or raw.get("price_floor") or "0",
                "price_ceiling": row.get("price_ceiling") or raw.get("price_ceiling") or "0",
                "be_delay_ms": row.get("be_delay_ms")
                if row.get("be_delay_ms") is not None
                else raw.get("be_delay_ms", 0),
                "be_bps": raw.get("be_bps"),
                "reentry_cooldown_ms": raw.get("reentry_cooldown_ms"),
                "reentry_bps": raw.get("reentry_bps"),
                "post_be_cooldown_ms": raw.get("post_be_cooldown_ms"),
            }
        )
        try:
            status = ChaseStatus(row.get("status") or "stopped")
        except ValueError:
            status = ChaseStatus.STOPPED
        from mayedge.algos.ledger import Ledger

        ledger = Ledger.from_persist(
            {
                "next_clip": row.get("next_clip"),
                "next_fill": row.get("next_fill"),
                "trade_ids": row.get("trade_ids") or set(),
                "trade_qty_by_clip": row.get("trade_qty_by_clip") or {},
                "clips": row.get("clips") or [],
                "fills": row.get("fills") or [],
            }
        )
        runtime = GridRuntime.from_json(runtime_raw if isinstance(runtime_raw, dict) else {})
        for clip in ledger.clips:
            if clip.seq in runtime.handled_fill_qty:
                continue
            if clip.status != "live":
                runtime.handled_fill_qty[clip.seq] = min(clip.filled, clip.qty)
        self._state = GridState(
            status=status,
            params=params,
            runtime=runtime,
            market_index=int(row.get("market_index") or 0),
            symbol=str(row.get("symbol") or ""),
            filled=_dec(row.get("filled") or "0"),
            remaining=_dec(row.get("remaining") or "0"),
            quote_action=str(row.get("quote_action") or Action.PAUSE.value),
            reason=row.get("reason"),
            rest_price=_dec(row["rest_price"]) if row.get("rest_price") is not None else None,
            rest_qty=_dec(row["rest_qty"]) if row.get("rest_qty") is not None else None,
            error=row.get("error"),
            algo_id=str(row.get("algo_id") or ""),
            created_at=int(row.get("created_at") or 0),
            ledger=ledger,
        )
        self._cois = {c.client_order_index for c in ledger.clips}
        self._handled_clip_seqs = {c.seq for c in ledger.clips if c.status == "filled"}
        self._stop.clear()
        self._wake.clear()

    async def start(
        self,
        *,
        algo_id: str,
        market_index: int,
        params: GridParams,
    ) -> None:
        meta = self._exec().get_market_by_index(market_index)
        if not meta:
            raise ValueError("Unknown market")
        if params.max_inventory <= 0 or params.display_qty <= 0:
            raise ValueError("Max inventory and clip must be > 0")
        if params.profit_bps <= 0:
            raise ValueError("Profit bps must be > 0")
        if params.price_floor >= params.price_ceiling:
            raise ValueError("Floor must be below ceiling")

        bid_s, ask_s = self._exec().best_bid_ask(market_index)
        ref = (
            _dec(bid_s)
            if bid_s
            else (_dec(ask_s) if ask_s else (params.price_floor + params.price_ceiling) / 2)
        )
        check_notional(params.max_inventory, ref, settings.max_order_notional)

        self._state = GridState(
            status=ChaseStatus.RUNNING,
            params=params,
            market_index=market_index,
            symbol=meta.symbol,
            remaining=params.max_inventory,
            algo_id=algo_id,
            created_at=grid_util.now_ms(),
        )
        self._cois.clear()
        self._handled_clip_seqs.clear()
        self._seed_inventory()
        try:
            await self._evaluate()
        except Exception:
            await self.stop()
            raise
        if self._state.status == ChaseStatus.RUNNING:
            self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            while not self._stop.is_set():
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), timeout=1.0)
                self._wake.clear()
                if self._stop.is_set():
                    break
                if (
                    self._state.status == ChaseStatus.ERROR
                    and self._state.error in GRID_AUTO_RESUME
                ):
                    with contextlib.suppress(Exception):
                        await self.unpause()
                    continue
                if self._state.status in (ChaseStatus.PAUSED, ChaseStatus.ERROR):
                    continue
                try:
                    await self._evaluate()
                except Exception as e:
                    if _is_rate_limit(e) or _is_invalid_nonce(e):
                        self._handle_tx_err(e)
                        continue
                    logger.exception("chase-grid error")
                    self._state.status = ChaseStatus.ERROR
                    self._state.error = str(e)
                    await self._cancel_algo_orders()
                    self._publish()
                    return
        except asyncio.CancelledError:
            raise

    def on_gateway(self, msg: dict[str, Any]) -> None:
        if self._state.status not in ACTIVE_STATUSES:
            return
        kind = msg.get("type")
        if kind == "account_trades":
            trades = msg.get("trades") or []
            if trades:
                self._pending_trades.extend(trades)
                self._wake.set()
            return
        if self._state.status != ChaseStatus.RUNNING:
            return
        book = (
            kind in ("order_book", "order_book_snapshot", "order_book_delta")
            and msg.get("market_index") == self._state.market_index
        )
        if book or kind == "account":
            self._wake.set()

    async def pause(self) -> None:
        if self._state.status != ChaseStatus.RUNNING:
            raise ValueError(f"cannot pause status={self._state.status}")
        complete = await self._cancel_algo_orders()
        if complete:
            self._state.status = ChaseStatus.PAUSED
            self._state.quote_action = Action.PAUSE.value
            self._state.reason = "user_paused"
            self._state.error = None
        else:
            self._state.status = ChaseStatus.ERROR
            self._state.error = "pause: cancel incomplete"
        self._wake.set()
        self._publish()

    async def unpause(self) -> None:
        if self._state.status not in (ChaseStatus.PAUSED, ChaseStatus.ERROR):
            raise ValueError(f"cannot unpause status={self._state.status}")
        if not await self._rearm_from_venue():
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._run())
            else:
                self._wake.set()
            self._publish()
            return
        self._state.status = ChaseStatus.RUNNING
        self._state.reason = None
        self._state.error = None
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())
        else:
            self._wake.set()
        await self._evaluate()
        self._publish()

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        complete = await self._cancel_algo_orders()
        if self._state.status in (ChaseStatus.RUNNING, ChaseStatus.PAUSED, ChaseStatus.ERROR):
            if complete:
                self._state.status = ChaseStatus.STOPPED
                self._finish()
            else:
                self._state.status = ChaseStatus.ERROR
                self._state.error = self._state.error or "stop: cancel incomplete"
                self._publish()

    async def drain_for_shutdown(self) -> None:
        if self._state.status not in ACTIVE_STATUSES:
            return
        self._stop.set()
        self._wake.set()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._state.status not in (ChaseStatus.RUNNING, ChaseStatus.ERROR):
            return
        complete = await self._cancel_algo_orders()
        if self._state.status == ChaseStatus.RUNNING:
            if complete:
                self._state.quote_action = Action.PAUSE.value
                self._state.reason = "shutdown"
            else:
                self._state.status = ChaseStatus.ERROR
                self._state.error = "shutdown: cancel incomplete"
        self._publish()

    async def resume(self) -> None:
        if self._state.status not in ACTIVE_STATUSES:
            raise ValueError(f"cannot resume status={self._state.status}")
        if not self._state.symbol:
            meta = self._exec().get_market_by_index(self._state.market_index)
            if meta:
                self._state.symbol = meta.symbol
        if not await self._rearm_from_venue():
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._run())
            self._publish()
            return
        if self._state.status == ChaseStatus.RUNNING:
            self._task = asyncio.create_task(self._run())
            await self._evaluate()
