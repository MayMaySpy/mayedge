from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from mayedge import db as store
from mayedge.lighter.models import MarketMeta
from mayedge.numbers import fmt_decimal

logger = logging.getLogger(__name__)

_LIQ_RING = 500
_LIQ_KINDS = frozenset({"liquidation", "deleverage"})


def _int_id(raw: Any) -> int:
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def _dec(raw: Any) -> Decimal:
    try:
        d = Decimal(str(raw if raw is not None else "0"))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")
    return d if d.is_finite() else Decimal("0")


def taker_order_id(raw: dict[str, Any]) -> int:
    """Liquidation engine is the taker — group fills of that order, not each match."""
    maker_ask = bool(raw.get("is_maker_ask") or raw.get("isAsk"))
    if maker_ask:
        return _int_id(raw.get("bid_id", raw.get("bid_id_str")))
    return _int_id(raw.get("ask_id", raw.get("ask_id_str")))


def liquidation_group_id(raw: dict[str, Any], *, market_index: int, kind: str) -> str:
    oid = taker_order_id(raw)
    if oid:
        return f"{market_index}:{kind}:{oid}"
    tid = _int_id(raw.get("trade_id", raw.get("id")))
    return f"{market_index}:{kind}:t{tid}"


@dataclass
class _LiqGroup:
    group_id: str
    market_index: int
    symbol: str
    kind: str
    side: str
    price: Decimal
    size: Decimal
    usd: Decimal
    ts: int
    fill_ids: set[int] = field(default_factory=set)

    def add_fill(self, *, trade_id: int, size: Decimal, usd: Decimal, ts: int) -> None:
        if trade_id in self.fill_ids:
            return
        self.fill_ids.add(trade_id)
        self.size += size
        self.usd += usd
        if self.size > 0:
            self.price = self.usd / self.size
        if ts and (not self.ts or ts < self.ts):
            self.ts = ts

    def public(self) -> dict[str, Any]:
        usd = fmt_decimal(self.usd)
        return {
            "trade_id": self.group_id,
            "market_index": self.market_index,
            "symbol": self.symbol,
            "kind": self.kind,
            "side": self.side,
            "price": fmt_decimal(self.price) or "0",
            "size": fmt_decimal(self.size) or "0",
            "usd_amount": usd,
            "fill_count": len(self.fill_ids),
            "timestamp": self.ts,
        }


class LiquidationFeed:
    """In-memory liquidation ring + SQLite persistence.

    Venue trades are per-match. One liquidation order hitting N makers is N
    trade_ids — we group by the taker order so alerts/tape count liquidations.
    """

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
        self._groups: dict[str, _LiqGroup] = {}

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

    def hydrate(self) -> None:
        """Load the recent SQLite window into the ring so reconnects are not empty."""
        if not self._persist or self._ring:
            return
        try:
            rows = store.list_liquidations(limit=_LIQ_RING * 8)
        except Exception:
            logger.exception("failed to hydrate liquidations")
            return
        if not rows:
            return
        seen: set[int] = set()
        for row in reversed(rows):
            try:
                tid = int(row["trade_id"])
            except (TypeError, ValueError):
                continue
            if not tid or tid in seen:
                continue
            seen.add(tid)
            self._credit_stored(row, tid)
        self._seen_ids = seen
        self._rebuild_ring()

    def ingest(
        self,
        market_index: int,
        rows: list[Any],
        *,
        get_market: Callable[[int], MarketMeta | None],
    ) -> None:
        meta = get_market(market_index)
        symbol = meta.symbol if meta else f"M{market_index}"
        fills: list[dict[str, Any]] = []
        changed: dict[str, _LiqGroup] = {}
        for t in rows:
            if not isinstance(t, dict):
                continue
            trade_id = _int_id(t.get("trade_id", t.get("id")))
            if not trade_id or trade_id in self._seen_ids:
                continue
            kind = str(t.get("type") or "liquidation")
            if kind not in _LIQ_KINDS:
                kind = "liquidation"
            side = "sell" if t.get("is_maker_ask") or t.get("isAsk") else "buy"
            ts = self._ts_ms(t.get("timestamp", t.get("time", 0)))
            size = _dec(t.get("size") or t.get("amount"))
            price = _dec(t.get("price"))
            usd = _dec(t.get("usd_amount"))
            if usd <= 0:
                usd = price * size
            mi = market_index
            sym = symbol
            if t.get("market_id") is not None:
                parsed_mi = _int_id(t.get("market_id"))
                if parsed_mi:
                    mi = parsed_mi
                    m2 = get_market(mi)
                    if m2:
                        sym = m2.symbol
            gid = liquidation_group_id(t, market_index=mi, kind=kind)
            grp = self._groups.get(gid)
            if grp is None:
                grp = _LiqGroup(
                    group_id=gid,
                    market_index=mi,
                    symbol=sym,
                    kind=kind,
                    side=side,
                    price=price,
                    size=Decimal("0"),
                    usd=Decimal("0"),
                    ts=ts,
                )
                self._groups[gid] = grp
            grp.add_fill(trade_id=trade_id, size=size, usd=usd, ts=ts)
            self._seen_ids.add(trade_id)
            fills.append(
                {
                    "trade_id": trade_id,
                    "group_id": gid,
                    "market_index": mi,
                    "symbol": sym,
                    "kind": kind,
                    "side": side,
                    "price": fmt_decimal(price) or "0",
                    "size": fmt_decimal(size) or "0",
                    "usd_amount": fmt_decimal(usd),
                    "ts": ts,
                }
            )
            changed[gid] = grp

        if not fills:
            return

        if len(self._seen_ids) > _LIQ_RING * 4:
            keep: set[int] = set()
            for g in self._groups.values():
                keep.update(g.fill_ids)
            self._seen_ids = keep

        if self._persist:
            try:
                store.insert_liquidations(fills)
            except Exception:
                logger.exception("failed to persist liquidations")

        self._rebuild_ring()
        public = [g.public() for g in changed.values()]
        public.sort(key=lambda e: int(e.get("timestamp") or 0), reverse=True)
        self._broadcast({"type": "liquidations", "items": public})

    def _credit_stored(self, row: dict[str, Any], trade_id: int) -> None:
        kind = str(row.get("kind") or "liquidation")
        if kind not in _LIQ_KINDS:
            kind = "liquidation"
        mi = _int_id(row.get("market_index"))
        gid = str(row.get("group_id") or "") or f"{mi}:{kind}:t{trade_id}"
        size = _dec(row.get("size"))
        price = _dec(row.get("price"))
        usd = _dec(row.get("usd_amount"))
        if usd <= 0:
            usd = price * size
        ts = _int_id(row.get("timestamp", row.get("ts")))
        grp = self._groups.get(gid)
        if grp is None:
            grp = _LiqGroup(
                group_id=gid,
                market_index=mi,
                symbol=str(row.get("symbol") or f"M{mi}"),
                kind=kind,
                side=str(row.get("side") or "buy"),
                price=price,
                size=Decimal("0"),
                usd=Decimal("0"),
                ts=ts,
            )
            self._groups[gid] = grp
        grp.add_fill(trade_id=trade_id, size=size, usd=usd, ts=ts)

    def _rebuild_ring(self) -> None:
        ranked = sorted(
            (g.public() for g in self._groups.values()),
            key=lambda r: int(r.get("timestamp") or 0),
            reverse=True,
        )
        self._ring = ranked[:_LIQ_RING]
        keep = {r["trade_id"] for r in self._ring}
        self._groups = {k: v for k, v in self._groups.items() if k in keep}

    def recent(self) -> list[dict[str, Any]]:
        return list(self._ring)
