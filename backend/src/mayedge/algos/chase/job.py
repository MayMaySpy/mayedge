from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from mayedge.algos.chase import util
from mayedge.algos.chase.execution import ChaseExecution
from mayedge.algos.chase.fills import may_invent_fill
from mayedge.algos.chase.iceberg import (
    ALGO_ID,
    ALGO_VERSION,
    Action,
    ChaseIcebergParams,
)
from mayedge.algos.chase.place import ChasePlaceMixin
from mayedge.algos.chase.state import (
    ACTIVE_STATUSES,
    ChaseBookView,
    ChaseState,
    ChaseStatus,
)
from mayedge.algos.chase.util import (
    _dec,
    _fmt,
    _is_invalid_nonce,
    _is_rate_limit,
)
from mayedge.algos.ledger import Ledger
from mayedge.config import settings
from mayedge.numbers import check_notional

logger = logging.getLogger(__name__)

__all__ = [
    "ACTIVE_STATUSES",
    "ALGO_ID",
    "ALGO_VERSION",
    "ChaseBookView",
    "ChaseIcebergRunner",
    "ChaseState",
    "ChaseStatus",
    "may_invent_fill",
]


class ChaseIcebergRunner(ChasePlaceMixin):
    """One chase job. ChaseBook owns many of these."""

    def __init__(self, book: ChaseBookView) -> None:
        self._book = book
        self._state = ChaseState()
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

    @property
    def state(self) -> ChaseState:
        return self._state

    def snapshot(self, s: ChaseState | None = None) -> dict[str, Any]:
        s = s or self._state
        self._reconcile_master()
        p = s.params
        live = s.ledger.working()
        return {
            "type": "algo",
            "id": ALGO_ID,
            "algo_type": ALGO_ID,
            "version": ALGO_VERSION,
            "algo_id": s.algo_id or None,
            "status": s.status.value,
            "market_index": s.market_index,
            "symbol": s.symbol,
            "reduce_only": s.reduce_only,
            "side": p.side if p else None,
            "qty": _fmt(p.qty) if p else None,
            "display_qty": _fmt(p.display_qty) if p else None,
            "offset_bps": _fmt(p.offset_bps) if p else None,
            "price_floor": _fmt(p.price_floor) if p else None,
            "price_ceiling": _fmt(p.price_ceiling) if p else None,
            "remaining": _fmt(s.remaining),
            "filled": _fmt(s.filled),
            "quote_action": s.quote_action,
            "reason": s.reason,
            "rest_price": _fmt(s.rest_price),
            "rest_qty": _fmt(s.rest_qty),
            "working_coi": live.client_order_index if live else None,
            "working_order_index": str(live.order_index) if live and live.order_index else None,
            "error": s.error,
            "created_at": s.created_at or None,
            **s.ledger.to_dict(),
        }

    def _publish(self) -> None:
        self._book.publish()

    def _finish(self) -> None:
        self._book.finish(self)

    def hydrate_from_row(self, row: dict[str, Any]) -> None:
        """Rebuild in-memory state from a DB row (does not start the loop)."""
        side = row.get("side")
        if side not in ("buy", "sell"):
            raise ValueError(f"unrecoverable chase row {row.get('algo_id')}: bad side")
        for key in ("qty", "display_qty", "offset_bps", "price_floor", "price_ceiling"):
            if row.get(key) is None:
                raise ValueError(f"unrecoverable chase row {row.get('algo_id')}: missing {key}")
        params = ChaseIcebergParams(
            side=side,
            qty=_dec(row["qty"]),
            display_qty=_dec(row["display_qty"]),
            offset_bps=_dec(row["offset_bps"]),
            price_floor=_dec(row["price_floor"]),
            price_ceiling=_dec(row["price_ceiling"]),
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
        self._state = ChaseState(
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
        self._reconcile_master()

    async def resume(self) -> None:
        """Continue a hydrated RUNNING/ERROR/PAUSED job after process restart."""
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
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._run())
            logger.info(
                "restored error chase job %s market=%s remaining=%s (awaiting unpause)",
                self._state.algo_id,
                self._state.symbol or self._state.market_index,
                self._state.remaining,
            )
            self._publish()
            return
        if self._state.status == ChaseStatus.PAUSED:
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._run())
            logger.info(
                "restored paused chase job %s market=%s remaining=%s",
                self._state.algo_id,
                self._state.symbol or self._state.market_index,
                self._state.remaining,
            )
            self._publish()
            return
        if self._state.status != ChaseStatus.RUNNING:
            raise ValueError(f"cannot resume status={self._state.status}")
        try:
            await self._evaluate()
        except Exception:
            logger.exception("chase resume evaluate failed for %s", self._state.algo_id)
            self._state.status = ChaseStatus.ERROR
            self._state.error = "resume evaluate failed"
            self._publish()
            return
        if self._state.status == ChaseStatus.RUNNING:
            self._task = asyncio.create_task(self._run())
            logger.info(
                "restored chase job %s market=%s remaining=%s",
                self._state.algo_id,
                self._state.symbol or self._state.market_index,
                self._state.remaining,
            )

    async def pause(self) -> None:
        """User pause: pull clips and hold the master until unpause."""
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
        """User resume after pause or error — start quoting again."""
        if self._state.status not in (ChaseStatus.PAUSED, ChaseStatus.ERROR):
            raise ValueError(f"cannot unpause status={self._state.status}")
        if not await self._rearm_from_venue():
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
            logger.exception("chase unpause evaluate failed for %s", self._state.algo_id)
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
        if self._state.status != ChaseStatus.RUNNING:
            return
        kind = msg.get("type")
        if kind == "account_trades":
            trades = msg.get("trades") or []
            if trades:
                self._pending_trades.extend(trades)
                self._wake.set()
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
        params: ChaseIcebergParams,
        reduce_only: bool = False,
    ) -> None:
        meta = self._exec().get_market_by_index(market_index)
        if not meta:
            raise ValueError("Unknown market")
        if params.qty <= 0 or params.display_qty <= 0:
            raise ValueError("Size and display qty must be > 0")
        if params.price_floor >= params.price_ceiling:
            raise ValueError("Floor must be below ceiling")
        if params.offset_bps < 0:
            raise ValueError("offset_bps must be ≥ 0")

        ref_price = self._parent_ref_price(params, market_index)
        check_notional(params.qty, ref_price, settings.max_order_notional)

        self._state = ChaseState(
            status=ChaseStatus.RUNNING,
            params=params,
            market_index=market_index,
            symbol=meta.symbol,
            reduce_only=reduce_only,
            remaining=params.qty,
            algo_id=algo_id,
            created_at=util.now_ms(),
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
        try:
            await self._evaluate()
        except Exception:
            await self.stop()
            raise
        if self._state.status == ChaseStatus.RUNNING:
            self._task = asyncio.create_task(self._run())

    async def drain_for_shutdown(self) -> None:
        """Pull venue clips before process exit; parent state persists for restore."""
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
                if self._state.status in (ChaseStatus.PAUSED, ChaseStatus.ERROR):
                    continue
                try:
                    await self._evaluate()
                except Exception as e:
                    if _is_rate_limit(e) or _is_invalid_nonce(e):
                        self._handle_tx_err(e)
                        continue
                    logger.exception("chase iceberg error")
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
