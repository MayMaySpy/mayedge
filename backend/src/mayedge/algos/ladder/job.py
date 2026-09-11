from __future__ import annotations

import asyncio
import contextlib
import logging
from decimal import Decimal
from typing import Any

from mayedge.algos.chase.config import AUTO_RESUME_ERRORS, STOP_CANCEL_GAP_S, STOP_CANCEL_TRIES
from mayedge.algos.chase.execution import ChaseExecution
from mayedge.algos.chase.fills import may_invent_fill
from mayedge.algos.chase.iceberg import Action, leftover_is_dust
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
from mayedge.algos.ladder import util as ladder_util
from mayedge.algos.ladder.config import MIN_PLACE_GAP_MS
from mayedge.algos.ladder.plan import (
    ALGO_ID,
    ALGO_VERSION,
    LadderParams,
    Rung,
    select_rungs_to_place,
    sort_by_closeness,
)
from mayedge.algos.ladder.state import LadderBookView, LadderState
from mayedge.algos.ladder.util import _ladder_order_keys
from mayedge.algos.ledger import Clip, Ledger
from mayedge.config import settings
from mayedge.numbers import check_notional

logger = logging.getLogger(__name__)


class LadderRunner(ChasePlaceMixin[LadderBookView, LadderState]):
    """One ladder job — keep-N live rungs on static prices."""

    def __init__(self, book: LadderBookView) -> None:
        self._book = book
        self._state = LadderState()
        self._cois: set[int] = set()
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._lock = asyncio.Lock()
        self._canceling = False
        self._last_tx_ms = 0
        self._backoff_until = 0
        self._backoff_reason: str | None = None
        self._pending_trades: list[dict[str, Any]] = []
        self._missing_refreshed: set[int] = set()
        self._unproven_retry_at = 0

    @property
    def state(self) -> LadderState:
        return self._state

    def _orders_cancel_keys(self, orders: Any) -> set[tuple[int, int]]:
        return set(_ladder_order_keys(orders, self._cois))

    def snapshot(self, s: LadderState | None = None) -> dict[str, Any]:
        st = s if s is not None else self._state
        self._reconcile_master()
        p = st.params
        live = st.ledger.live_clips()
        per_rung = p.rung_list[0].qty if p and p.rung_list else None
        lo = hi = None
        if p:
            lo = min(p.price_from, p.price_to)
            hi = max(p.price_from, p.price_to)
        return {
            "type": "algo",
            "id": ALGO_ID,
            "algo_type": ALGO_ID,
            "version": ALGO_VERSION,
            "algo_id": st.algo_id or None,
            "status": st.status.value,
            "market_index": st.market_index,
            "symbol": st.symbol,
            "reduce_only": st.reduce_only,
            "side": p.side if p else None,
            "qty": _fmt(p.qty) if p else None,
            "display_qty": _fmt(per_rung) if per_rung is not None else None,
            "offset_bps": None,
            "price_floor": _fmt(lo) if lo is not None else None,
            "price_ceiling": _fmt(hi) if hi is not None else None,
            "remaining": _fmt(st.remaining),
            "filled": _fmt(st.filled),
            "quote_action": st.quote_action,
            "reason": st.reason,
            "rest_price": _fmt(st.rest_price),
            "rest_qty": _fmt(st.rest_qty),
            "working_coi": live[-1].client_order_index if live else None,
            "working_order_index": (
                str(live[-1].order_index) if live and live[-1].order_index else None
            ),
            "error": st.error,
            "created_at": st.created_at or None,
            "params_json": p.to_json() if p else {},
            **st.ledger.to_dict(),
        }

    def _publish(self) -> None:
        self._book.publish()

    def _finish(self) -> None:
        self._book.finish(self)

    def _sync_rest_from_live(self) -> None:
        params = self._state.params
        live = self._state.ledger.live_clips()
        if not live or not params:
            self._state.rest_price = None
            self._state.rest_qty = None
            return
        by_price = {r.price: r for r in params.rung_list}
        live_rungs = [by_price[c.price] for c in live if c.price in by_price]
        if live_rungs:
            closest = sort_by_closeness(live_rungs, params.side)[0]
            self._state.rest_price = closest.price
        total_rem = sum((c.remaining for c in live), Decimal("0"))
        self._state.rest_qty = total_rem if total_rem > 0 else Decimal(len(live))

    def hydrate_from_row(self, row: dict[str, Any]) -> None:
        side = row.get("side")
        if side not in ("buy", "sell"):
            raise ValueError(f"unrecoverable ladder row {row.get('algo_id')}: bad side")
        raw = row.get("params_json") or {}
        if not isinstance(raw, dict):
            raw = {}
        if not raw.get("rung_list"):
            raise ValueError(f"unrecoverable ladder row {row.get('algo_id')}: missing rung_list")
        params = LadderParams.from_json(
            raw,
            side=side,
            qty=_dec(row.get("qty") or raw.get("qty") or "0"),
            price_from=_dec(raw.get("price_from") or row.get("price_floor") or "0"),
            price_to=_dec(raw.get("price_to") or row.get("price_ceiling") or "0"),
            rungs=int(raw.get("rungs") or 0),
            window=int(raw.get("window") or 10),
        )
        try:
            status = ChaseStatus(row.get("status") or "stopped")
        except ValueError:
            status = ChaseStatus.STOPPED
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
        self._state = LadderState(
            status=status,
            params=params,
            market_index=int(row.get("market_index") or 0),
            symbol=str(row.get("symbol") or ""),
            reduce_only=bool(row.get("reduce_only")),
            remaining=_dec(row.get("remaining") or "0"),
            filled=_dec(row.get("filled") or "0"),
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
        self._stop.clear()
        self._wake.clear()
        self._last_tx_ms = 0
        self._backoff_until = 0
        self._backoff_reason = None
        self._canceling = False
        self._pending_trades.clear()
        self._missing_refreshed.clear()
        self._unproven_retry_at = 0
        self._reconcile_master()

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
        if self._state.status == ChaseStatus.ERROR:
            if self._state.error in AUTO_RESUME_ERRORS:
                self._state.status = ChaseStatus.RUNNING
                self._state.reason = None
                self._state.error = None
                if self._task is None or self._task.done():
                    self._task = asyncio.create_task(self._run())
                try:
                    await self._evaluate()
                except Exception:
                    logger.exception("ladder auto-resume evaluate failed for %s", self._state.algo_id)
                    self._state.status = ChaseStatus.ERROR
                    self._state.error = "resume evaluate failed"
                    self._publish()
                    return
                self._publish()
                return
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._run())
            self._publish()
            return
        if self._state.status == ChaseStatus.PAUSED:
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._run())
            self._publish()
            return
        if self._state.status != ChaseStatus.RUNNING:
            raise ValueError(f"cannot resume status={self._state.status}")
        try:
            await self._evaluate()
        except Exception:
            logger.exception("ladder resume evaluate failed for %s", self._state.algo_id)
            self._state.status = ChaseStatus.ERROR
            self._state.error = "resume evaluate failed"
            self._publish()
            return
        if self._state.status == ChaseStatus.RUNNING:
            self._task = asyncio.create_task(self._run())

    async def pause(self) -> None:
        if self._state.status != ChaseStatus.RUNNING:
            raise ValueError(f"cannot pause status={self._state.status}")
        complete = await self._cancel_algo_orders()
        if complete:
            self._state.status = ChaseStatus.PAUSED
            self._state.quote_action = Action.PAUSE.value
            self._state.reason = "user_paused"
            self._state.rest_price = None
            self._state.rest_qty = None
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
        try:
            await self._evaluate()
        except Exception:
            logger.exception("ladder unpause evaluate failed for %s", self._state.algo_id)
            self._state.status = ChaseStatus.ERROR
            self._state.error = "unpause evaluate failed"
            self._publish()
            return
        self._publish()

    def _next_coi(self) -> int:
        coi = self._book.alloc_coi()
        self._cois.add(coi)
        return coi

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
            kind
            in (
                "order_book",
                "order_book_snapshot",
                "order_book_delta",
            )
            and msg.get("market_index") == self._state.market_index
        )
        if book or kind == "account":
            self._wake.set()

    async def start(
        self,
        *,
        algo_id: str,
        market_index: int,
        params: LadderParams,
        reduce_only: bool = False,
    ) -> None:
        meta = self._exec().get_market_by_index(market_index)
        if not meta:
            raise ValueError("Unknown market")
        ref = (params.price_from + params.price_to) / 2
        check_notional(params.qty, ref, settings.max_order_notional)
        self._state = LadderState(
            status=ChaseStatus.RUNNING,
            params=params,
            market_index=market_index,
            symbol=meta.symbol,
            reduce_only=reduce_only,
            remaining=params.qty,
            algo_id=algo_id,
            created_at=ladder_util.now_ms(),
        )
        self._cois.clear()
        self._stop.clear()
        self._wake.clear()
        self._last_tx_ms = 0
        self._backoff_until = 0
        self._backoff_reason = None
        self._canceling = False
        self._pending_trades.clear()
        self._missing_refreshed.clear()
        self._unproven_retry_at = 0
        try:
            await self._evaluate()
        except Exception:
            await self.stop()
            raise
        if self._state.status == ChaseStatus.RUNNING:
            self._task = asyncio.create_task(self._run())

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
                self._state.rest_price = None
                self._state.rest_qty = None
                self._state.error = None
            else:
                self._state.status = ChaseStatus.ERROR
                self._state.error = "shutdown: cancel incomplete"
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
                    and self._state.error in AUTO_RESUME_ERRORS
                ):
                    try:
                        await self.unpause()
                    except Exception:
                        logger.exception("ladder auto-resume failed for %s", self._state.algo_id)
                    continue
                if self._state.status in (ChaseStatus.PAUSED, ChaseStatus.ERROR):
                    continue
                try:
                    await self._evaluate()
                except Exception as e:
                    if _is_rate_limit(e) or _is_invalid_nonce(e):
                        self._handle_tx_err(e)
                        continue
                    logger.exception("ladder error")
                    self._state.status = ChaseStatus.ERROR
                    self._state.error = str(e)
                    await self._cancel_algo_orders()
                    self._publish()
                    return
                if self._state.status in (ChaseStatus.PAUSED, ChaseStatus.ERROR):
                    continue
                if self._state.status != ChaseStatus.RUNNING:
                    break
        except asyncio.CancelledError:
            raise

    def _exec(self) -> ChaseExecution:
        return self._book.execution()

    async def _cancel_clip(self, clip: Clip) -> None:
        await self._sync_fills()
        if clip.status != "live":
            return
        if not self._exec().enabled:
            self._state.ledger.close_missing(clip, canceling=True, now=ladder_util.now_ms())
            self._reconcile_master()
            return
        coi = clip.client_order_index
        for attempt in range(STOP_CANCEL_TRIES):
            target = self._cancel_target(clip)
            if target is None:
                if await self._coi_open_on_venue(coi):
                    self._reconcile_master()
                    return
                now = ladder_util.now_ms()
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
                self._reconcile_master()
                return
            mi, oid = target
            self._canceling = True
            try:
                try:
                    await self._exec().cancel_order(mi, oid)
                    self._last_tx_ms = ladder_util.now_ms()
                except Exception as e:
                    if _is_order_not_found(e) or _is_min_size(e):
                        pass
                    elif self._handle_tx_err(e):
                        return
                    else:
                        logger.exception("ladder cancel failed")
                        if await self._coi_open_on_venue(coi):
                            self._reconcile_master()
                            return
                        raise
            finally:
                self._canceling = False
            if not await self._coi_open_on_venue(coi):
                self._state.ledger.close_missing(clip, canceling=True, now=ladder_util.now_ms())
                self._reconcile_master()
                return
            if attempt + 1 < STOP_CANCEL_TRIES:
                await asyncio.sleep(STOP_CANCEL_GAP_S)
        self._reconcile_master()

    async def _place_rung(self, rung: Rung) -> bool:
        params = self._state.params
        if params is None:
            return False
        coi = self._next_coi()
        try:
            await self._exec().create_limit_order(
                market_index=self._state.market_index,
                side=params.side,
                size=_fmt(rung.qty) or "0",
                price=_fmt(rung.price) or "0",
                time_in_force="post_only",
                reduce_only=self._state.reduce_only,
                client_order_index=coi,
            )
        except ValueError as e:
            if _is_min_size(e) or _is_would_cross(e):
                return False
            if self._handle_tx_err(e):
                return False
            raise
        except Exception as e:
            if _is_min_size(e) or _is_would_cross(e):
                return False
            if self._handle_tx_err(e):
                return False
            raise
        self._last_tx_ms = ladder_util.now_ms()
        found = self._find_open(coi)
        idx = int(found["order_index"]) if found and found.get("order_index") else None
        self._state.ledger.place(
            client_order_index=coi,
            price=rung.price,
            qty=rung.qty,
            now=ladder_util.now_ms(),
            order_index=idx,
            side=params.side,
        )
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
            self._reconcile_master()
            min_qty = self._clip_min_qty()
            if self._state.remaining <= 0 or leftover_is_dust(self._state.remaining, min_qty):
                await self._finish_done()
                return

            now = ladder_util.now_ms()
            if self._unproven_retry_at:
                if self._state.ledger.live_clips():
                    self._unproven_retry_at = 0
                elif now < self._unproven_retry_at:
                    self._state.quote_action = Action.PAUSE.value
                    if self._state.reason != "trades_reconcile_failed":
                        self._state.reason = "unproven_missing_clip"
                    self._state.rest_price = None
                    self._state.rest_qty = None
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
                self._sync_rest_from_live()
                self._publish()
                return

            ladder_params = self._state.params
            assert ladder_params is not None
            for clip in list(self._state.ledger.live_clips()):
                if self._working_crosses(clip.price, view, ladder_params.side):
                    await self._cancel_clip(clip)

            if now < self._backoff_until:
                self._state.quote_action = Action.PAUSE.value
                self._state.reason = self._backoff_reason or "rate_limited"
                self._sync_rest_from_live()
                self._publish()
                return

            live = self._state.ledger.live_clips()
            to_place = select_rungs_to_place(
                ladder_params,
                ledger=self._state.ledger,
                live_count=len(live),
                bid=view.bid,
                ask=view.ask,
            )
            placed_any = False
            for rung in to_place:
                now = ladder_util.now_ms()
                if now < self._backoff_until:
                    break
                if self._last_tx_ms > 0 and now - self._last_tx_ms < MIN_PLACE_GAP_MS:
                    break
                if await self._place_rung(rung):
                    placed_any = True

            self._sync_rest_from_live()
            live = self._state.ledger.live_clips()
            if live:
                self._state.quote_action = Action.REST.value
                self._state.reason = None
            elif not placed_any:
                self._state.quote_action = Action.PAUSE.value
                if not self._state.reason:
                    self._state.reason = "would_cross" if to_place else "waiting"

            if (
                self._state.remaining <= 0 or leftover_is_dust(self._state.remaining, min_qty)
            ) and not self._state.ledger.live_clips():
                await self._finish_done()
                return

            self._publish()
