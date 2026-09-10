"""Quote evaluation, cancel, and post-only placement for chase-iceberg."""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Any

from mayedge.algos.chase import util
from mayedge.algos.chase.config import (
    ACK_WAIT_MS,
    MIN_REQUOTE_MS,
    NONCE_COOLDOWN_MS,
    RATE_LIMIT_COOLDOWN_MS,
    STOP_CANCEL_GAP_S,
    STOP_CANCEL_TRIES,
    UNPROVEN_RETRY_MS,
)
from mayedge.algos.chase.fills import ChaseFillMixin
from mayedge.algos.chase.iceberg import (
    Action,
    ChaseIcebergParams,
    MarketView,
    decide,
)
from mayedge.algos.chase.state import ChaseStatus
from mayedge.algos.chase.util import (
    _chase_order_keys,
    _dec,
    _fmt,
    _is_invalid_nonce,
    _is_min_size,
    _is_order_not_found,
    _is_rate_limit,
    _is_would_cross,
)

logger = logging.getLogger(__name__)


class ChasePlaceMixin(ChaseFillMixin):
    """Requote loop: decide, amend live clip, or place post-only child."""

    _lock: asyncio.Lock
    _stop: asyncio.Event
    _last_tx_ms: int
    _backoff_until: int
    _backoff_reason: str | None
    _unproven_retry_at: int

    def _publish(self) -> None: ...
    def _finish(self) -> None: ...
    def _next_coi(self) -> int: ...

    def _parent_ref_price(self, params: ChaseIcebergParams, market_index: int) -> Decimal:
        """Reference price for parent notional cap: book mid, else band mid."""
        bid_s, ask_s = self._exec().best_bid_ask(market_index)
        if bid_s and ask_s:
            bid = _dec(bid_s)
            ask = _dec(ask_s)
            if bid > 0 and ask > 0:
                return (bid + ask) / 2
        mid = (params.price_floor + params.price_ceiling) / 2
        if mid <= 0:
            raise ValueError("Cannot price chase order")
        return mid

    def _market_view(self) -> MarketView | None:
        meta = self._exec().get_market_by_index(self._state.market_index)
        if not meta:
            return None
        bid_s, ask_s = self._exec().best_bid_ask(self._state.market_index)
        bid = _dec(bid_s) if bid_s else None
        ask = _dec(ask_s) if ask_s else None
        tick = Decimal(10) ** -meta.price_decimals
        qty_step = Decimal(10) ** -meta.size_decimals
        min_qty = self._clip_min_qty()
        return MarketView(bid=bid, ask=ask, tick=tick, min_qty=min_qty, qty_step=qty_step)

    def _account_ready(self) -> bool:
        ex = self._exec()
        live_fn = ex.account_ws_live
        account_live = live_fn() if live_fn is not None else True
        return account_live and ex.orders_hydrated()

    async def _pull_and_wait(self, reason: str) -> None:
        """Pull the venue child; stay RUNNING until feeds/band allow requote."""
        if self._state.ledger.working() is not None:
            await self._cancel_working()
        self._state.quote_action = Action.PAUSE.value
        self._state.reason = reason
        self._state.rest_price = None
        self._state.rest_qty = None
        self._sync_rest_from_live()
        self._publish()

    def _working_crosses(self, price: Decimal, view: MarketView, side: str) -> bool:
        if side == "buy":
            return view.ask is not None and price >= view.ask
        return view.bid is not None and price <= view.bid

    def _on_rate_limit(self, err: BaseException) -> None:
        logger.warning("chase rate limited: %s", err)
        self._on_transient(err, "rate_limited")

    def _on_transient(self, err: BaseException, reason: str) -> None:
        cool = NONCE_COOLDOWN_MS if reason == "invalid_nonce" else RATE_LIMIT_COOLDOWN_MS
        self._backoff_until = util.now_ms() + cool
        self._backoff_reason = reason
        self._state.quote_action = Action.PAUSE.value
        self._state.reason = reason
        self._publish()

    def _handle_tx_err(self, err: BaseException) -> bool:
        if _is_rate_limit(err):
            self._on_rate_limit(err)
            return True
        if _is_invalid_nonce(err):
            logger.warning("chase invalid nonce: %s", err)
            self._on_transient(err, "invalid_nonce")
            return True
        return False

    def _cancel_target(self, clip: Any) -> tuple[int, int] | None:
        found = self._find_open(clip.client_order_index)
        if found is not None:
            oid = int(found.get("order_index") or 0)
            mi = int(found.get("market_index") or self._state.market_index)
            if oid:
                return mi, oid
        if clip.order_index:
            return self._state.market_index, int(clip.order_index)
        return None

    def _modify_index(self, clip: Any) -> int | None:
        # Lighter's modify example keys the order by client_order_index.
        if clip.client_order_index:
            return int(clip.client_order_index)
        target = self._cancel_target(clip)
        if target is not None:
            return target[1]
        return None

    def _sync_rest_from_live(self) -> None:
        """Chart / blotter follow the venue clip, never the desired quote."""
        live = self._state.ledger.working()
        if live is None:
            self._state.rest_price = None
            self._state.rest_qty = None
            return
        self._state.rest_price = live.price
        self._state.rest_qty = live.remaining

    async def _place_working(self, quote: Any) -> None:
        params = self._state.params
        if params is None:
            return
        if await self._venue_children_blocking_place():
            self._state.quote_action = Action.PAUSE.value
            self._state.reason = "child_still_open"
            self._publish()
            return
        coi = self._next_coi()
        try:
            await self._exec().create_limit_order(
                market_index=self._state.market_index,
                side=params.side,
                size=_fmt(quote.qty) or "0",
                price=_fmt(quote.price) or "0",
                time_in_force="post_only",
                reduce_only=self._state.reduce_only,
                client_order_index=coi,
            )
        except ValueError as e:
            if _is_min_size(e):
                self._state.quote_action = Action.PAUSE.value
                self._state.reason = "below_min_qty"
                self._publish()
                return
            if _is_would_cross(e):
                self._state.quote_action = Action.PAUSE.value
                self._state.reason = "would_cross"
                self._publish()
                return
            if self._handle_tx_err(e):
                return
            raise
        except Exception as e:
            if _is_min_size(e):
                self._state.quote_action = Action.PAUSE.value
                self._state.reason = "below_min_qty"
                self._publish()
                return
            if self._handle_tx_err(e):
                return
            raise
        self._last_tx_ms = util.now_ms()
        found = self._find_open(coi)
        idx = int(found["order_index"]) if found and found.get("order_index") else None
        self._state.ledger.place(
            client_order_index=coi,
            price=quote.price,
            qty=quote.qty,
            now=util.now_ms(),
            order_index=idx,
        )
        self._publish()

    def _hold_clip(self, reason: str) -> None:
        """Leave the venue clip put; cooldown so we don't hammer amend."""
        self._last_tx_ms = util.now_ms()
        self._state.reason = reason
        self._sync_rest_from_live()
        self._publish()

    async def _abandon_and_replace_working(self, quote: Any) -> None:
        """Cancel an un-amendable leftover and rest the quoted clip."""
        await self._cancel_working()
        if self._state.ledger.working() is None:
            await self._place_working(quote)
        self._sync_rest_from_live()
        self._publish()

    async def _modify_working(self, clip: Any, quote: Any) -> None:
        idx = self._modify_index(clip)
        if idx is None:
            self._state.ledger.close_missing(clip, canceling=True, now=util.now_ms())
            self._reconcile_master()
            await self._place_working(quote)
            return
        # Send remaining size (not 0). NilOrderBaseAmount is valid on the
        # wire but the matching engine then leaves the venue order put.
        rem = clip.remaining if clip.remaining > 0 else quote.qty
        if rem is None or rem <= 0:
            self._state.ledger.close_missing(clip, canceling=True, now=util.now_ms())
            self._reconcile_master()
            await self._place_working(quote)
            return
        view = self._market_view()
        if view is not None and rem < view.min_qty:
            await self._abandon_and_replace_working(quote)
            return
        size = _fmt(rem) or "0"
        try:
            await self._exec().modify_order(
                market_index=self._state.market_index,
                order_index=idx,
                price=_fmt(quote.price) or "0",
                size=size,
            )
        except ValueError as e:
            if _is_would_cross(e):
                # Keep the resting clip — the current price is still valid.
                self._hold_clip("would_cross")
                return
            if _is_min_size(e):
                await self._abandon_and_replace_working(quote)
                return
            if _is_order_not_found(e):
                self._state.ledger.close_missing(clip, canceling=True, now=util.now_ms())
                self._reconcile_master()
                await self._place_working(quote)
                return
            if self._handle_tx_err(e):
                return
            logger.warning("chase modify failed, keeping clip: %s", e)
            self._hold_clip(self._state.reason or "requote_wait")
            return
        except Exception as e:
            if _is_order_not_found(e):
                self._state.ledger.close_missing(clip, canceling=True, now=util.now_ms())
                self._reconcile_master()
                await self._place_working(quote)
                return
            if self._handle_tx_err(e):
                return
            logger.warning("chase modify failed, keeping clip: %s", e)
            self._hold_clip(self._state.reason or "requote_wait")
            return
        self._last_tx_ms = util.now_ms()
        self._state.ledger.amend(clip, price=quote.price, now=util.now_ms())
        self._sync_rest_from_live()
        self._publish()

    async def _cancel_working(self) -> None:
        await self._sync_fills()
        clip = self._state.ledger.working()
        if clip is None:
            return
        if not self._exec().enabled:
            self._state.ledger.close_missing(clip, canceling=True, now=util.now_ms())
            self._reconcile_master()
            return
        coi = clip.client_order_index
        for attempt in range(STOP_CANCEL_TRIES):
            target = self._cancel_target(clip)
            if target is None:
                if await self._coi_open_on_venue(coi):
                    self._reconcile_master()
                    return
                now = util.now_ms()
                if self._may_invent_fill(clip, now):
                    self._close_missing_clip(clip, now=now, assume_fill=True)
                else:
                    self._state.ledger.close_missing(clip, canceling=True, now=now)
                self._reconcile_master()
                return
            mi, oid = target
            self._canceling = True
            try:
                try:
                    await self._exec().cancel_order(mi, oid)
                    self._last_tx_ms = util.now_ms()
                except Exception as e:
                    if _is_order_not_found(e) or _is_min_size(e):
                        pass
                    elif self._handle_tx_err(e):
                        return
                    else:
                        logger.exception("chase cancel failed")
                        if await self._coi_open_on_venue(coi):
                            self._reconcile_master()
                            return
                        raise
            finally:
                self._canceling = False
            if not await self._coi_open_on_venue(coi):
                self._state.ledger.close_missing(clip, canceling=True, now=util.now_ms())
                self._reconcile_master()
                return
            if attempt + 1 < STOP_CANCEL_TRIES:
                await asyncio.sleep(STOP_CANCEL_GAP_S)
        self._reconcile_master()

    async def _finish_done(self) -> None:
        await self._cancel_algo_orders()
        self._state.status = ChaseStatus.DONE
        self._state.quote_action = Action.DONE.value
        self._state.reason = "filled"
        self._state.rest_price = None
        self._state.rest_qty = None
        self._reconcile_master()
        self._finish()
        self._stop.set()

    def _abandon_live_clips(self) -> None:
        now = util.now_ms()
        for clip in self._state.ledger.clips:
            if clip.status == "live":
                self._state.ledger.close_missing(clip, canceling=True, now=now)

    def _ledger_cancel_keys(self) -> set[tuple[int, int]]:
        keys: set[tuple[int, int]] = set()
        mi = self._state.market_index
        for clip in self._state.ledger.clips:
            if clip.status != "live":
                continue
            if clip.order_index:
                keys.add((mi, int(clip.order_index)))
            elif clip.client_order_index:
                keys.add((mi, int(clip.client_order_index)))
        return keys

    def _orders_cancel_keys(self, orders: Any) -> set[tuple[int, int]]:
        return set(_chase_order_keys(orders, self._cois))

    async def _venue_child_keys(self, *, refresh: bool) -> set[tuple[int, int]]:
        keys = self._ledger_cancel_keys()
        payload = self._exec().cached_account_payload() or {}
        keys.update(self._orders_cancel_keys(payload.get("open_orders")))
        if refresh and self._exec().enabled:
            try:
                summary = await self._exec().get_account_summary()
                keys.update(self._orders_cancel_keys(summary.open_orders))
            except Exception:
                logger.exception("chase stop: failed to refresh open orders")
        return keys

    async def _remaining_child_keys(self) -> set[tuple[int, int]]:
        if not self._exec().enabled:
            return set()
        try:
            summary = await self._exec().get_account_summary()
            return self._orders_cancel_keys(summary.open_orders)
        except Exception:
            logger.exception("chase stop: remaining-orders refresh failed")
            payload = self._exec().cached_account_payload() or {}
            return self._orders_cancel_keys(payload.get("open_orders"))

    async def _coi_open_on_venue(self, coi: int) -> bool:
        """True when REST still lists this job COI as an open child."""
        rows = await self._refresh_open_orders()
        return self._find_in_rows(rows, coi) is not None

    async def _venue_children_blocking_place(self) -> bool:
        """True when REST shows any job COI still open — do not place a new clip."""
        keys = await self._remaining_child_keys()
        return len(keys) > 0

    async def _cancel_one(self, mi: int, idx: int) -> str:
        try:
            await self._exec().cancel_order(mi, idx)
            self._last_tx_ms = util.now_ms()
            return "ok"
        except Exception as e:
            if _is_order_not_found(e):
                return "gone"
            if _is_rate_limit(e) or _is_invalid_nonce(e):
                logger.warning("chase stop: transient cancelling %s/%s: %s", mi, idx, e)
                return "transient"
            logger.warning("chase stop: cancel %s/%s failed: %s", mi, idx, e)
            return "fail"

    async def _cancel_algo_orders(self) -> bool:
        """Pull every venue child. REST truth, not the lagging WS cache."""
        self._canceling = True
        try:
            if not self._exec().enabled:
                self._abandon_live_clips()
                return True
            pending = await self._venue_child_keys(refresh=True)
            for attempt in range(STOP_CANCEL_TRIES):
                if not pending:
                    self._abandon_live_clips()
                    return True
                transient = False
                for mi, idx in pending:
                    if await self._cancel_one(mi, idx) == "transient":
                        transient = True
                pending = await self._remaining_child_keys()
                if not pending:
                    self._abandon_live_clips()
                    return True
                if attempt + 1 < STOP_CANCEL_TRIES and transient:
                    await asyncio.sleep(STOP_CANCEL_GAP_S)
            return False
        finally:
            self._canceling = False

    async def _rearm_from_venue(self) -> bool:
        """Credit REST trades, pull venue children, close live ledger clips."""
        if not await self._credit_rest_trades():
            self._state.status = ChaseStatus.RUNNING
            self._state.error = None
            self._state.quote_action = Action.PAUSE.value
            self._state.reason = "trades_reconcile_failed"
            self._unproven_retry_at = util.now_ms() + UNPROVEN_RETRY_MS
            self._state.rest_price = None
            self._state.rest_qty = None
            self._publish()
            return False
        complete = await self._cancel_algo_orders()
        if not complete:
            self._state.status = ChaseStatus.ERROR
            self._state.error = "rearm: cancel incomplete"
            self._state.quote_action = Action.PAUSE.value
            self._state.reason = "rearm: cancel incomplete"
            self._publish()
            return False
        return True

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
            if self._state.remaining <= 0:
                await self._finish_done()
                return

            if self._state.status == ChaseStatus.ERROR:
                return

            now = util.now_ms()
            if self._unproven_retry_at:
                if self._state.ledger.working() is not None:
                    self._unproven_retry_at = 0
                elif now < self._unproven_retry_at:
                    self._state.quote_action = Action.PAUSE.value
                    if self._state.reason != "trades_reconcile_failed":
                        self._state.reason = "unproven_missing_clip"
                    self._state.rest_price = None
                    self._state.rest_qty = None
                    self._publish()
                    return
                else:
                    if not await self._credit_rest_trades():
                        self._unproven_retry_at = now + UNPROVEN_RETRY_MS
                        self._state.quote_action = Action.PAUSE.value
                        self._state.reason = "trades_reconcile_failed"
                        self._state.rest_price = None
                        self._state.rest_qty = None
                        self._publish()
                        return
                    self._unproven_retry_at = 0
                    self._reconcile_master()
                    if self._state.remaining <= 0:
                        await self._finish_done()
                        return

            if not self._exec().is_book_synced(self._state.market_index):
                await self._pull_and_wait("book_unsynced")
                return

            if not self._account_ready():
                await self._pull_and_wait("account_unsynced")
                return

            view = self._market_view()
            if not view:
                await self._pull_and_wait("no_market")
                return

            live = self._state.ledger.working()

            quote = decide(self._state.params, view, self._state.remaining)
            self._state.quote_action = quote.action.value
            self._state.reason = quote.reason
            self._sync_rest_from_live()

            if quote.action == Action.DONE:
                await self._finish_done()
                return

            must_pull = live is not None and self._working_crosses(
                live.price, view, self._state.params.side
            )
            rate_limited = now < self._backoff_until
            cooling = (
                self._last_tx_ms > 0 and now - self._last_tx_ms < MIN_REQUOTE_MS
            )

            if quote.action == Action.PAUSE:
                if self._state.ledger.working() is not None:
                    await self._cancel_working()
                self._sync_rest_from_live()
                self._publish()
                return

            assert quote.price is not None and quote.qty is not None
            live = self._state.ledger.working()

            # Empty book: rest now. Cooldown only throttles amends, not the first clip.
            if live is None:
                if rate_limited:
                    self._state.quote_action = Action.PAUSE.value
                    self._state.reason = self._backoff_reason or "rate_limited"
                    self._publish()
                    return
                await self._place_working(quote)
                self._sync_rest_from_live()
                self._publish()
                return

            if live.price == quote.price:
                self._publish()
                return

            waiting_ack = not live.seen_on_book and now - live.placed_at < ACK_WAIT_MS
            if waiting_ack:
                self._publish()
                return

            if must_pull:
                await self._cancel_working()
                self._sync_rest_from_live()
                self._publish()
                return

            if rate_limited:
                self._state.reason = self._backoff_reason or "rate_limited"
                self._publish()
                return
            if cooling:
                self._state.reason = "requote_wait"
                self._publish()
                return

            await self._modify_working(live, quote)
