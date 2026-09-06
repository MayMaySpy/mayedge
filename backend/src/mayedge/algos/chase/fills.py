"""Fill sync and invent-fill policy for chase-iceberg clips."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from mayedge.algos.chase import util
from mayedge.algos.chase.config import (
    REST_TRADES_MAX_PAGES,
    REST_TRADES_PAGE_LIMIT,
    STALE_ACK_MS,
)
from mayedge.algos.chase.execution import ChaseExecution
from mayedge.algos.chase.iceberg import Action
from mayedge.algos.chase.state import ChaseBookView, ChaseState, ChaseStatus
from mayedge.algos.chase.util import _dec
from mayedge.algos.ledger import Clip, Ledger

logger = logging.getLogger(__name__)


def may_invent_fill(
    clip: Clip,
    now: int,
    *,
    ledger: Ledger,
    orders_hydrated: bool,
    grace_ms: int,
) -> bool:
    """Invent-fill only when trade or open-sync evidence already credits the clip.

    Accumulate/distribute: never invent a full clip from silence alone — stall
    with ``unproven_missing_clip`` instead of risking overshoot.
    """
    if not orders_hydrated:
        return False
    return ledger.should_fill_when_missing(clip)


class ChaseFillMixin:
    """Drain trades, sync open orders, reconcile master qty."""

    _book: ChaseBookView
    _state: ChaseState
    _cois: set[int]
    _pending_trades: list[dict[str, Any]]
    _canceling: bool
    _missing_refreshed: set[int]

    def _exec(self) -> ChaseExecution: ...
    def _publish(self) -> None: ...

    def _may_invent_fill(self, clip: Any, now: int) -> bool:
        return may_invent_fill(
            clip,
            now,
            ledger=self._state.ledger,
            orders_hydrated=self._exec().orders_hydrated(),
            grace_ms=self._book.missing_fill_grace_ms,
        )

    def _reconcile_master(self) -> None:
        """Master filled/remaining follow per-clip filled (capped).

        Also heal clip.filled from the blotter tape when they drift — every
        Fill event must be reflected on its clip or remaining freezes at qty.
        """
        if not self._state.params:
            return
        qty = self._state.params.qty
        by_seq: dict[int, Decimal] = {}
        for f in self._state.ledger.fills:
            by_seq[f.clip_seq] = by_seq.get(f.clip_seq, Decimal("0")) + f.qty
        for c in self._state.ledger.clips:
            taped = by_seq.get(c.seq, Decimal("0"))
            if taped > c.filled:
                c.filled = min(c.qty, taped)
        filled = min(self._state.ledger.working_filled_total(), qty)
        self._state.filled = filled
        self._state.remaining = max(Decimal("0"), qty - filled)

    def _close_missing_clip(self, clip: Any, *, now: int, assume_fill: bool) -> Decimal:
        """Close a live clip. Fill remainder only when assume_fill is warranted."""
        if assume_fill:
            return self._state.ledger.close_missing(clip, canceling=False, now=now)
        self._state.ledger.close_missing(clip, canceling=True, now=now)
        return Decimal("0")

    def _drain_trades(self) -> None:
        if not self._pending_trades or not self._state.params:
            self._pending_trades.clear()
            return
        trades = self._pending_trades
        self._pending_trades = []
        now = util.now_ms()
        for t in trades:
            mi = int(t.get("market_index") or 0)
            if mi and mi != self._state.market_index:
                continue
            qty = _dec(t.get("size") or "0")
            if qty <= 0:
                continue
            candidates = [
                (int(t.get("bid_client_id") or 0), int(t.get("bid_id") or 0)),
                (int(t.get("ask_client_id") or 0), int(t.get("ask_id") or 0)),
            ]
            clip = None
            matched_oid = 0
            for coi, oid in candidates:
                if coi and coi in self._cois:
                    clip = self._state.ledger.find_clip(
                        client_order_index=coi, order_index=oid or None
                    )
                    matched_oid = oid
                    if clip is not None:
                        break
                if oid:
                    clip = self._state.ledger.find_clip(order_index=oid)
                    matched_oid = oid
                    if clip is not None:
                        break
            if clip is None:
                continue
            px = _dec(t.get("price") or "0")
            tid = int(t.get("trade_id") or 0) or None
            delta = self._state.ledger.apply_trade(
                clip,
                qty,
                now=now,
                price=px if px > 0 else None,
                trade_id=tid,
                order_index=matched_oid or None,
            )
            if delta > 0:
                self._reconcile_master()

    def _order_row(self, raw: Any) -> dict[str, Any] | None:
        if raw is None:
            return None
        if isinstance(raw, dict):
            coi = int(raw.get("client_order_index") or 0)
            if not coi:
                return None
            return raw
        coi = int(getattr(raw, "client_order_index", 0) or 0)
        if not coi:
            return None
        return {
            "client_order_index": coi,
            "order_index": getattr(raw, "order_index", None),
            "market_index": getattr(raw, "market_index", None),
            "remaining": getattr(raw, "remaining", "0"),
            "filled": getattr(raw, "filled", "0"),
        }

    def _find_in_rows(self, rows: Any, coi: int) -> dict[str, Any] | None:
        for raw in rows or []:
            row = self._order_row(raw)
            if row is not None and int(row.get("client_order_index") or 0) == coi:
                return row
        return None

    async def _refresh_open_orders(self) -> list[dict[str, Any]]:
        """One REST pull when WS cache may lag a vanish. Returns normalized rows."""
        ex = self._exec()
        if not ex.enabled:
            return []
        ex.kick_refresh()
        try:
            summary = await ex.get_account_summary()
        except Exception:
            logger.exception("chase REST open-order refresh failed")
            return []
        out: list[dict[str, Any]] = []
        for raw in getattr(summary, "open_orders", None) or []:
            row = self._order_row(raw)
            if row is not None:
                out.append(row)
        return out

    def _fail_unproven_missing(self, clip: Clip, *, now: int) -> None:
        self._state.ledger.close_missing(clip, canceling=True, now=now)
        self._reconcile_master()
        self._state.status = ChaseStatus.ERROR
        self._state.error = "unproven_missing_clip"
        self._state.quote_action = Action.PAUSE.value
        self._state.reason = "unproven_missing_clip"
        self._state.rest_price = None
        self._state.rest_qty = None
        self._publish()

    async def _credit_rest_trades(self) -> bool:
        """Credit REST trades for this market before re-arming venue children."""
        ex = self._exec()
        get_trades = ex.get_account_trades
        if get_trades is None:
            return True
        cursor: str | None = None
        try:
            for page in range(REST_TRADES_MAX_PAGES):
                resp = await get_trades(
                    market_id=self._state.market_index,
                    cursor=cursor,
                    limit=REST_TRADES_PAGE_LIMIT,
                )
                trades = (
                    resp.get("trades")
                    if isinstance(resp, dict)
                    else getattr(resp, "trades", None)
                )
                if trades:
                    self._pending_trades.extend(trades)
                    self._drain_trades()
                next_cursor = (
                    resp.get("next_cursor")
                    if isinstance(resp, dict)
                    else getattr(resp, "next_cursor", None)
                )
                if not next_cursor:
                    return True
                cursor = str(next_cursor)
            logger.warning(
                "chase REST trades reconcile hit page cap %s for market=%s",
                REST_TRADES_MAX_PAGES,
                self._state.market_index,
            )
            return False
        except Exception:
            logger.exception("chase REST trades reconcile failed")
            return False

    async def _resolve_vanished_clip(self, clip: Clip, *, now: int) -> None:
        """Clip absent from WS cache — REST truth, then credit or ERROR."""
        rest_rows = await self._refresh_open_orders()
        found = self._find_in_rows(rest_rows, clip.client_order_index)
        if found is not None:
            rem = _dec(found.get("remaining") or "0")
            filled = _dec(found.get("filled") or "0")
            idx = int(found.get("order_index") or 0) or None
            self._state.ledger.apply_open(
                clip,
                rem,
                now=now,
                order_index=idx,
                book_filled=filled if filled > 0 else None,
            )
            self._reconcile_master()
            return
        if self._may_invent_fill(clip, now):
            self._close_missing_clip(clip, now=now, assume_fill=True)
            self._reconcile_master()
            return
        if not await self._credit_rest_trades():
            self._fail_unproven_missing(clip, now=now)
            return
        if self._may_invent_fill(clip, now):
            self._close_missing_clip(clip, now=now, assume_fill=True)
            self._reconcile_master()
            return
        if not self._exec().orders_hydrated():
            self._reconcile_master()
            return
        self._fail_unproven_missing(clip, now=now)

    async def _sync_fills(self) -> None:
        self._drain_trades()
        clip = self._state.ledger.working()
        if clip is None:
            self._reconcile_master()
            return
        found = self._find_open(clip.client_order_index)
        now = util.now_ms()
        if found is None:
            if self._canceling:
                self._state.ledger.close_missing(clip, canceling=True, now=now)
                self._reconcile_master()
                return
            if not clip.seen_on_book:
                if now - clip.placed_at < STALE_ACK_MS:
                    self._reconcile_master()
                    return
                await self._resolve_vanished_clip(clip, now=now)
                return
            if self._may_invent_fill(clip, now):
                self._close_missing_clip(clip, now=now, assume_fill=True)
                self._reconcile_master()
                return
            if clip.missing_since is None:
                clip.missing_since = now
                self._reconcile_master()
                return
            if now - clip.missing_since < self._book.missing_fill_grace_ms:
                self._reconcile_master()
                return
            if clip.seq not in self._missing_refreshed:
                self._missing_refreshed.add(clip.seq)
            await self._resolve_vanished_clip(clip, now=now)
            return
        rem = _dec(found.get("remaining") or "0")
        filled = _dec(found.get("filled") or "0")
        idx = int(found.get("order_index") or 0) or None
        self._state.ledger.apply_open(
            clip,
            rem,
            now=now,
            order_index=idx,
            book_filled=filled if filled > 0 else None,
        )
        self._reconcile_master()

    def _find_open(self, coi: int) -> dict[str, Any] | None:
        payload = self._exec().cached_account_payload() or {}
        for o in payload.get("open_orders") or []:
            if int(o.get("client_order_index") or 0) == coi:
                return o
        return None
