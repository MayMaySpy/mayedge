from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from mayedge import db as store
from mayedge.lighter.models import MarketMeta

logger = logging.getLogger(__name__)

_LIQ_RING = 500
_LIQ_KINDS = frozenset({"liquidation", "deleverage"})


class LiquidationFeed:
    """In-memory liquidation ring + SQLite persistence."""

    def __init__(
        self,
        broadcast: Callable[[dict[str, Any]], None],
        *,
        persist: bool = True,
    ) -> None:
        self._broadcast = broadcast
        self._persist = persist
        self._ring: list[dict[str, Any]] = []
        self._seen_ids: set[int] = set()

    @staticmethod
    def liq_kinds() -> frozenset[str]:
        return _LIQ_KINDS

    @staticmethod
    def _ts_ms(raw: Any) -> int:
        try:
            ts = int(raw or 0)
        except (TypeError, ValueError):
            return 0
        if ts <= 0:
            return 0
        if ts > 1e14:
            return ts // 1000
        if ts < 1e12:
            return ts * 1000
        return ts

    def ingest(
        self,
        market_index: int,
        rows: list[Any],
        *,
        get_market: Callable[[int], MarketMeta | None],
    ) -> None:
        meta = get_market(market_index)
        symbol = meta.symbol if meta else f"M{market_index}"
        events: list[dict[str, Any]] = []
        for t in rows:
            if not isinstance(t, dict):
                continue
            try:
                trade_id = int(t.get("trade_id") or t.get("id") or 0)
            except (TypeError, ValueError):
                trade_id = 0
            if not trade_id or trade_id in self._seen_ids:
                continue
            kind = str(t.get("type") or "liquidation")
            if kind not in _LIQ_KINDS:
                kind = "liquidation"
            side = "sell" if t.get("is_maker_ask") or t.get("isAsk") else "buy"
            ts = self._ts_ms(t.get("timestamp", t.get("time", 0)))
            usd = t.get("usd_amount")
            if usd is None:
                try:
                    usd = str(float(t.get("price") or 0) * float(t.get("size") or 0))
                except (TypeError, ValueError):
                    usd = None
            mi = market_index
            sym = symbol
            if t.get("market_id") is not None:
                try:
                    mi = int(t["market_id"])
                    m2 = get_market(mi)
                    if m2:
                        sym = m2.symbol
                except (TypeError, ValueError):
                    pass
            ev = {
                "trade_id": trade_id,
                "market_index": mi,
                "symbol": sym,
                "kind": kind,
                "side": side,
                "price": str(t.get("price") or "0"),
                "size": str(t.get("size") or "0"),
                "usd_amount": str(usd) if usd is not None else None,
                "ts": ts,
            }
            self._seen_ids.add(trade_id)
            events.append(ev)

        if not events:
            return

        events.sort(key=lambda e: e["ts"], reverse=True)

        if len(self._seen_ids) > _LIQ_RING * 4:
            keep = {e["trade_id"] for e in self._ring}
            keep.update(e["trade_id"] for e in events)
            self._seen_ids = keep

        if self._persist:
            try:
                store.insert_liquidations(events)
            except Exception:
                logger.exception("failed to persist liquidations")

        public = [
            {
                "trade_id": str(e["trade_id"]),
                "market_index": e["market_index"],
                "symbol": e["symbol"],
                "kind": e["kind"],
                "side": e["side"],
                "price": e["price"],
                "size": e["size"],
                "usd_amount": e["usd_amount"],
                "timestamp": e["ts"],
            }
            for e in events
        ]
        merged = public + self._ring
        by_id: dict[str, dict[str, Any]] = {}
        for row in merged:
            tid = str(row.get("trade_id") or "")
            if not tid:
                continue
            prev = by_id.get(tid)
            if prev is None or int(row.get("timestamp") or 0) >= int(prev.get("timestamp") or 0):
                by_id[tid] = row
        self._ring = sorted(
            by_id.values(),
            key=lambda r: int(r.get("timestamp") or 0),
            reverse=True,
        )[:_LIQ_RING]
        self._broadcast({"type": "liquidations", "items": public})

    def recent(self) -> list[dict[str, Any]]:
        return list(self._ring)
