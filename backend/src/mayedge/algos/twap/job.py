from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time
from decimal import Decimal
from typing import Any

from mayedge.algos.chase.execution import ChaseExecution
from mayedge.algos.chase.state import ACTIVE_STATUSES, ChaseStatus
from mayedge.algos.chase.util import _dec, _fmt, _is_order_not_found
from mayedge.algos.ledger import Ledger
from mayedge.algos.twap.plan import (
    ALGO_ID,
    ALGO_VERSION,
    AdvancedTwapParams,
    next_wait_s,
    order_count,
    skip_reason,
    slice_qty,
    slice_quote,
    validate_params,
)
from mayedge.config import settings
from mayedge.numbers import check_notional, fmt_decimal

logger = logging.getLogger(__name__)


def now_ms() -> int:
    return int(time.time() * 1000)


class AdvancedTwapRunner:
    """One desk-side TWAP job. AdvancedTwapBook owns many of these."""

    def __init__(self, book: Any) -> None:
        self._book = book
        self._exec_fn = book.execution
        self.status = ChaseStatus.STOPPED
        self.params: AdvancedTwapParams | None = None
        self.market_index = 0
        self.symbol = ""
        self.reduce_only = False
        self.remaining = Decimal("0")
        self.filled = Decimal("0")
        self.quote_action = "pause"
        self.reason: str | None = None
        self.rest_price: Decimal | None = None
        self.rest_qty: Decimal | None = None
        self.error: str | None = None
        self.algo_id = ""
        self.created_at = 0
        self.ledger = Ledger()
        self._cois: set[int] = set()
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._run_gate = asyncio.Event()
        self._run_gate.set()
        self._pending_trades: list[dict[str, Any]] = []
        self._rng = random.Random()

    def execution(self) -> ChaseExecution:
        return self._exec_fn()

    def snapshot(self) -> dict[str, Any]:
        self._reconcile()
        p = self.params
        live = self.ledger.working()
        display = self.rest_qty if self.rest_qty is not None else (p.qty if p else None)
        return {
            "type": "algo",
            "id": ALGO_ID,
            "algo_type": ALGO_ID,
            "version": ALGO_VERSION,
            "algo_id": self.algo_id or None,
            "status": self.status.value,
            "market_index": self.market_index,
            "symbol": self.symbol,
            "reduce_only": self.reduce_only,
            "side": p.side if p else None,
            "qty": _fmt(p.qty) if p else None,
            "display_qty": _fmt(display) if display is not None else None,
            "offset_bps": None,
            "price_floor": None,
            "price_ceiling": _fmt(p.max_price) if p and p.max_price is not None else None,
            "remaining": _fmt(self.remaining),
            "filled": _fmt(self.filled),
            "quote_action": self.quote_action,
            "reason": self.reason,
            "rest_price": _fmt(self.rest_price),
            "rest_qty": _fmt(self.rest_qty),
            "working_coi": live.client_order_index if live else None,
            "working_order_index": str(live.order_index) if live and live.order_index else None,
            "error": self.error,
            "created_at": self.created_at or None,
            "params_json": p.to_json() if p else {},
            **self.ledger.to_dict(),
        }

    def _publish(self) -> None:
        self._book.publish()

    def _finish(self) -> None:
        self._book.finish(self)

    def _reconcile(self) -> None:
        if not self.params:
            return
        qty = self.params.qty
        filled = min(self.ledger.working_filled_total(), qty)
        self.filled = filled
        self.remaining = max(Decimal("0"), qty - filled)

    def _u(self) -> float:
        return self._rng.random() if (self.params and self.params.randomize) else 0.5

    def _orders_left(self) -> int:
        p = self.params
        if not p:
            return 0
        total = order_count(p.duration_seconds, p.frequency_seconds)
        left = max(1, total - p.slices_done)
        if now_ms() >= p.deadline_at:
            return 1
        return left

    def _quotes(
        self, market_index: int | None = None
    ) -> tuple[Decimal | None, Decimal | None, Decimal | None, Decimal | None, Decimal | None]:
        mi = self.market_index if market_index is None else market_index
        meta = self.execution().get_market_by_index(mi)
        bid_s, ask_s = self.execution().best_bid_ask(mi)
        bid = _dec(bid_s) if bid_s else None
        ask = _dec(ask_s) if ask_s else None
        mid = (bid + ask) / 2 if bid and ask and bid > 0 and ask > 0 else None
        mark = None
        index = None
        if meta:
            if getattr(meta, "mark_price", None):
                mark = Decimal(str(meta.mark_price))
            if getattr(meta, "index_price", None):
                index = Decimal(str(meta.index_price))
            last = getattr(meta, "last_trade_price", None)
            if mark is None and last:
                mark = Decimal(str(last))
        if mark is None:
            mark = mid or bid or ask
        return bid, ask, mid, mark, index

    def on_gateway(self, msg: dict[str, Any]) -> None:
        if self.status != ChaseStatus.RUNNING:
            return
        kind = msg.get("type")
        if kind == "account_trades":
            trades = msg.get("trades") or []
            if trades:
                self._pending_trades.extend(trades)
        elif kind == "market_stats" or (
            kind in ("order_book", "order_book_snapshot", "order_book_delta")
            and msg.get("market_index") == self.market_index
        ):
            return

    def _drain_trades(self) -> None:
        trades = self._pending_trades
        self._pending_trades = []
        now = now_ms()
        for t in trades:
            mi = int(t.get("market_index") or 0)
            if mi and mi != self.market_index:
                continue
            qty = _dec(t.get("size") or "0")
            if qty <= 0:
                continue
            clip = None
            matched_oid = 0
            for coi, oid in (
                (int(t.get("bid_client_id") or 0), int(t.get("bid_id") or 0)),
                (int(t.get("ask_client_id") or 0), int(t.get("ask_id") or 0)),
            ):
                if coi and coi in self._cois:
                    clip = self.ledger.find_clip(client_order_index=coi, order_index=oid or None)
                    matched_oid = oid
                    if clip is not None:
                        break
                if oid:
                    clip = self.ledger.find_clip(order_index=oid)
                    matched_oid = oid
                    if clip is not None:
                        break
            if clip is None:
                continue
            px = _dec(t.get("price") or "0")
            tid = int(t.get("trade_id") or 0) or None
            self.ledger.apply_trade(
                clip,
                qty,
                now=now,
                price=px if px > 0 else None,
                trade_id=tid,
                order_index=matched_oid or None,
            )
        self._reconcile()

    async def _credit_trades(self) -> None:
        self._drain_trades()
        ex = self.execution()
        get_trades = ex.get_account_trades
        if get_trades is None:
            return
        try:
            resp = await get_trades(market_id=self.market_index, cursor=None, limit=50)
            trades = (
                resp.get("trades") if isinstance(resp, dict) else getattr(resp, "trades", None)
            )
            if trades:
                self._pending_trades.extend(trades)
                self._drain_trades()
        except Exception:
            logger.exception("twap REST trades failed for %s", self.algo_id)

    async def _cancel_live(self, *, assume_fill: bool = False) -> None:
        clip = self.ledger.working()
        if clip is None:
            return
        idx = clip.order_index or clip.client_order_index
        try:
            await self.execution().cancel_order(self.market_index, int(idx))
        except Exception as e:
            if not _is_order_not_found(e):
                logger.warning("twap cancel %s failed: %s", self.algo_id, e)
        now = now_ms()
        if assume_fill:
            clip.seen_on_book = True
            self.ledger.close_missing(clip, canceling=False, now=now)
        else:
            self.ledger.close_missing(clip, canceling=True, now=now)
        self._reconcile()
        self.rest_price = None
        self.rest_qty = None

    async def _wait(self, seconds: float) -> bool:
        if self._stop.is_set():
            return True
        if seconds <= 0:
            return False
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
            return True
        except TimeoutError:
            return False

    async def start(
        self,
        *,
        algo_id: str,
        market_index: int,
        params: AdvancedTwapParams,
        reduce_only: bool = False,
    ) -> None:
        validate_params(params)
        meta = self.execution().get_market_by_index(market_index)
        if not meta:
            raise ValueError("Unknown market")
        bid, ask, mid, mark, _index = self._quotes(market_index)
        ref = mid or mark
        if ref is None or ref <= 0:
            raise ValueError("Cannot price TWAP — no reference price")
        check_notional(params.qty, ref, settings.max_order_notional)
        now = now_ms()
        params.started_at = now
        params.deadline_at = now + params.duration_seconds * 1000
        params.slices_done = 0
        self.algo_id = algo_id
        self.market_index = market_index
        self.symbol = meta.symbol
        self.reduce_only = reduce_only
        self.params = params
        self.remaining = params.qty
        self.filled = Decimal("0")
        self.ledger = Ledger()
        self._cois.clear()
        self.created_at = now
        self.status = ChaseStatus.RUNNING
        self.error = None
        self._stop.clear()
        self._run_gate.set()
        await self._step()
        if self.status == ChaseStatus.RUNNING:
            self._task = asyncio.create_task(self._run())

    def hydrate_from_row(self, row: dict[str, Any]) -> None:
        side = row.get("side")
        if side not in ("buy", "sell"):
            raise ValueError(f"unrecoverable twap row {row.get('algo_id')}: bad side")
        qty = _dec(row.get("qty") or "0")
        raw = row.get("params_json") or {}
        if not isinstance(raw, dict):
            raw = {}
        params = AdvancedTwapParams.from_json(raw, side=side, qty=qty)
        if not params.duration_seconds:
            raise ValueError(f"unrecoverable twap row {row.get('algo_id')}: missing duration")
        try:
            status = ChaseStatus(row.get("status") or "stopped")
        except ValueError:
            status = ChaseStatus.STOPPED
        self.params = params
        self.status = status
        self.market_index = int(row.get("market_index") or 0)
        self.symbol = str(row.get("symbol") or "")
        self.reduce_only = bool(row.get("reduce_only"))
        self.remaining = _dec(row.get("remaining") or "0")
        self.filled = _dec(row.get("filled") or "0")
        self.quote_action = str(row.get("quote_action") or "pause")
        self.reason = row.get("reason")
        self.rest_price = _dec(row["rest_price"]) if row.get("rest_price") is not None else None
        self.rest_qty = _dec(row["rest_qty"]) if row.get("rest_qty") is not None else None
        self.error = row.get("error")
        self.algo_id = str(row.get("algo_id") or "")
        self.created_at = int(row.get("created_at") or 0)
        self.ledger = Ledger.from_persist(
            {
                "next_clip": row.get("next_clip"),
                "next_fill": row.get("next_fill"),
                "trade_ids": row.get("trade_ids") or set(),
                "trade_qty_by_clip": row.get("trade_qty_by_clip") or {},
                "clips": row.get("clips") or [],
                "fills": row.get("fills") or [],
            }
        )
        self._cois = {c.client_order_index for c in self.ledger.clips}
        self._stop.clear()
        self._run_gate.set()
        if status == ChaseStatus.PAUSED:
            self._run_gate.clear()
        self._reconcile()

    async def resume(self) -> None:
        if self.status not in ACTIVE_STATUSES:
            raise ValueError(f"cannot resume status={self.status}")
        if not self.symbol:
            meta = self.execution().get_market_by_index(self.market_index)
            if meta:
                self.symbol = meta.symbol
        p = self.params
        if p and now_ms() >= p.deadline_at and self.remaining <= 0:
            self.status = ChaseStatus.DONE
            self._finish()
            return
        if self.status == ChaseStatus.PAUSED:
            self._run_gate.clear()
        else:
            self._run_gate.set()
        await self._cancel_live()
        if self.status == ChaseStatus.RUNNING:
            await self._step()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())
        self._publish()

    async def pause(self) -> None:
        if self.status != ChaseStatus.RUNNING:
            raise ValueError(f"cannot pause status={self.status}")
        await self._cancel_live()
        self.status = ChaseStatus.PAUSED
        self.quote_action = "pause"
        self.reason = "user_paused"
        self.error = None
        self._run_gate.clear()
        self._publish()

    async def unpause(self) -> None:
        if self.status not in (ChaseStatus.PAUSED, ChaseStatus.ERROR):
            raise ValueError(f"cannot unpause status={self.status}")
        self.status = ChaseStatus.RUNNING
        self.reason = None
        self.error = None
        self._run_gate.set()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())
        await self._step()
        self._publish()

    async def drain_for_shutdown(self) -> None:
        if self.status not in ACTIVE_STATUSES:
            return
        self._stop.set()
        self._run_gate.set()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._cancel_live()
        if self.status == ChaseStatus.RUNNING:
            self.quote_action = "pause"
            self.reason = "shutdown"
        self._publish()

    async def stop(self) -> None:
        self._stop.set()
        self._run_gate.set()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._cancel_live()
        if self.status in (ChaseStatus.RUNNING, ChaseStatus.PAUSED, ChaseStatus.ERROR):
            self.status = ChaseStatus.STOPPED
            self._finish()

    async def _run(self) -> None:
        try:
            while not self._stop.is_set():
                await self._run_gate.wait()
                if self._stop.is_set():
                    break
                if self.status != ChaseStatus.RUNNING or not self.params:
                    if await self._wait(0.25):
                        break
                    continue
                wait = next_wait_s(self.params.frequency_seconds, self.params.randomize, self._u())
                if await self._wait(wait):
                    break
                if self.status != ChaseStatus.RUNNING:
                    continue
                try:
                    await self._step()
                except Exception as e:
                    logger.exception("advanced twap error")
                    self.status = ChaseStatus.ERROR
                    self.error = str(e)
                    await self._cancel_live()
                    self._publish()
                    return
        except asyncio.CancelledError:
            raise

    async def _step(self) -> None:
        if self.status != ChaseStatus.RUNNING or not self.params:
            return
        await self._credit_trades()
        self._reconcile()
        if self.remaining <= 0:
            self.status = ChaseStatus.DONE
            self.quote_action = "pause"
            self.reason = None
            self._finish()
            return
        p = self.params
        now = now_ms()
        bid, ask, mid, mark, index = self._quotes()
        if now >= p.deadline_at:
            skip = skip_reason(
                side=p.side,
                mark=mark,
                index=index,
                max_price=p.max_price,
                max_index_pct=None,
            )
            if skip:
                self.quote_action = "pause"
                self.reason = "deadline"
                self.status = ChaseStatus.STOPPED
                self._finish()
                return
            p.slices_done = max(p.slices_done, order_count(p.duration_seconds, p.frequency_seconds) - 1)
        else:
            skip = skip_reason(
                side=p.side,
                mark=mark,
                index=index,
                max_price=p.max_price,
                max_index_pct=p.max_index_pct,
            )
            if skip:
                self.quote_action = "pause"
                self.reason = skip
                self.rest_price = None
                self.rest_qty = None
                self._publish()
                return
        await self._cancel_live()
        qty = slice_qty(self.remaining, self._orders_left(), randomize=p.randomize, u=self._u())
        if qty <= 0:
            return
        quote = slice_quote(p.style, p.side, bid=bid, ask=ask, mid=mid, mark=mark)
        if p.max_price is not None and quote.get("price"):
            px = Decimal(str(quote["price"]))
            if p.side == "buy" and px > p.max_price:
                quote = {**quote, "price": str(p.max_price)}
            elif p.side == "sell" and px < p.max_price:
                quote = {**quote, "price": str(p.max_price)}
        await self._place(qty, quote, mark)
        p.slices_done += 1
        self._reconcile()
        if self.remaining <= 0:
            self.status = ChaseStatus.DONE
            self.quote_action = "pause"
            self.reason = None
            self._finish()

    def _slippage(self, mark: Decimal | None) -> float:
        p = self.params
        if not p or mark is None or mark <= 0 or p.max_price is None:
            return 0.01
        slip = float(abs(p.max_price - mark) / mark)
        return max(0.001, min(slip, 0.05))

    async def _place(self, qty: Decimal, quote: dict[str, str | None], mark: Decimal | None) -> None:
        p = self.params
        if not p:
            return
        coi = self._book.alloc_coi()
        self._cois.add(coi)
        size = fmt_decimal(qty) or "0"
        kind = quote.get("kind")
        now = now_ms()
        px = Decimal(str(quote["price"])) if quote.get("price") else (mark or Decimal("0"))
        clip = self.ledger.place(
            client_order_index=coi,
            price=px if px > 0 else Decimal("0"),
            qty=qty,
            now=now,
            side=p.side,
        )
        self.rest_qty = qty
        self.rest_price = px if px > 0 else None
        self.quote_action = "rest" if kind != "market" else "rest"
        self.reason = None
        ex = self.execution()
        if kind == "market":
            await ex.create_market_order(
                self.market_index,
                p.side,
                size,
                self._slippage(mark),
                self.reduce_only,
                client_order_index=coi,
            )
            clip.seen_on_book = True
            self.ledger.close_missing(clip, canceling=False, now=now_ms())
            self._reconcile()
            self.rest_price = None
            self.rest_qty = None
            self._publish()
            return
        price = quote.get("price")
        if not price:
            raise ValueError("No price for TWAP slice")
        tif = quote.get("tif") or "ioc"
        result = await ex.create_limit_order(
            self.market_index,
            p.side,
            size,
            price,
            tif,
            self.reduce_only,
            client_order_index=coi,
        )
        idx = result.get("order_index") if isinstance(result, dict) else None
        if not idx:
            payload = ex.cached_account_payload() or {}
            for row in payload.get("open_orders") or []:
                raw = row if isinstance(row, dict) else None
                coi_row = int((raw or {}).get("client_order_index") or getattr(row, "client_order_index", 0) or 0)
                if coi_row == coi:
                    idx = (raw or {}).get("order_index") or getattr(row, "order_index", None)
                    break
        if idx:
            clip.order_index = int(idx)
        self._publish()
        if tif == "ioc":
            await self._wait(0.35)
            await self._credit_trades()
            if clip.status == "live":
                clip.seen_on_book = True
                self.ledger.close_missing(clip, canceling=True, now=now_ms())
                self._reconcile()
            self.rest_price = None
            self.rest_qty = None
            self._publish()
