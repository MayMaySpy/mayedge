from __future__ import annotations

from typing import Any

from mayedge.config import settings
from mayedge.lighter.gateway import gateway
from mayedge.lighter.models import OpenOrder, Position, imf_to_leverage, to_float


def g(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def parse_position(raw: Any) -> Position | None:
    size = str(g(raw, "position", g(raw, "size", "0")) or "0")
    try:
        if abs(float(size)) == 0:
            return None
    except (TypeError, ValueError):
        return None
    mi = int(g(raw, "market_id", g(raw, "market_index", 0)) or 0)
    meta = gateway.get_market_by_index(mi)
    symbol = str(g(raw, "symbol", "") or (meta.symbol if meta else str(mi)))
    qty = abs(to_float(size))
    try:
        sign = int(g(raw, "sign", 1))
    except (TypeError, ValueError):
        sign = 1
    is_short = sign <= 0
    magnitude = size.lstrip("+-")
    signed = f"-{magnitude}" if is_short else magnitude
    value = to_float(g(raw, "position_value", 0))
    mark = None
    if meta and (meta.last_trade_price or meta.mark_price):
        mark = meta.last_trade_price or meta.mark_price
    elif qty:
        mark = abs(value) / qty
    return Position(
        market_index=mi,
        symbol=symbol,
        size=signed,
        entry_price=str(g(raw, "avg_entry_price", "0") or "0"),
        mark_price=str(mark or 0),
        unrealized_pnl=str(g(raw, "unrealized_pnl", "0") or "0"),
        leverage=imf_to_leverage(g(raw, "initial_margin_fraction", None)),
        margin_mode="cross" if int(g(raw, "margin_mode", 0) or 0) == 0 else "isolated",
        liquidation_price=str(g(raw, "liquidation_price", "") or ""),
        funding_paid=str(g(raw, "total_funding_paid_out", "0") or "0"),
        allocated_margin=str(g(raw, "allocated_margin", "0") or "0"),
        side="short" if is_short else "long",
    )


def parse_order(raw: Any) -> OpenOrder | None:
    open_status = {"", "open", "pending", "in-progress", "partial", "partial-filled"}
    status = str(g(raw, "status", "open") or "open").lower()
    initial = str(g(raw, "initial_base_amount", g(raw, "size", "0")) or "0")
    filled_raw = g(raw, "filled_base_amount", g(raw, "filled", None))
    remaining_raw = g(raw, "remaining_base_amount", g(raw, "remaining", None))
    if remaining_raw is None or remaining_raw == "":
        if filled_raw not in (None, ""):
            remaining = str(max(0.0, to_float(initial) - to_float(filled_raw)))
        else:
            remaining = initial
    else:
        remaining = str(remaining_raw)
    filled = str(filled_raw) if filled_raw not in (None, "") else ""
    if not filled:
        try:
            filled = str(max(0.0, to_float(initial) - to_float(remaining)))
        except (TypeError, ValueError):
            filled = "0"
    if status not in open_status:
        return None
    if to_float(remaining) <= 0:
        return None
    mi = int(g(raw, "market_index", g(raw, "market_id", 0)) or 0)
    meta = gateway.get_market_by_index(mi)
    is_ask = g(raw, "is_ask", None)
    if is_ask is None:
        side = str(g(raw, "side", "buy") or "buy").lower()
    else:
        side = "sell" if is_ask else "buy"
    return OpenOrder(
        order_index=int(g(raw, "order_index", 0) or 0),
        client_order_index=int(g(raw, "client_order_index", 0) or 0),
        market_index=mi,
        symbol=meta.symbol if meta else str(mi),
        side=side,
        price=str(g(raw, "price", "0") or "0"),
        size=initial,
        remaining=remaining,
        filled=filled,
        order_type=str(g(raw, "type", g(raw, "order_type", "limit")) or "limit"),
        reduce_only=bool(g(raw, "reduce_only", False)),
    )


def iter_trade_rows(raw: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(raw, dict):
        for mi_key, items in raw.items():
            batch = items if isinstance(items, list) else [items]
            for item in batch:
                if not isinstance(item, dict):
                    continue
                row = dict(item)
                if row.get("market_id") is None and row.get("market_index") is None:
                    try:
                        row["market_id"] = int(mi_key)
                    except (TypeError, ValueError):
                        pass
                rows.append(row)
    elif isinstance(raw, list):
        rows.extend(item for item in raw if isinstance(item, dict))
    return rows


def _nonzero_amount(value: Any) -> str | None:
    if value is None or value == "":
        return None
    try:
        if abs(float(value)) == 0:
            return None
    except (TypeError, ValueError):
        return None
    return str(value)


def realized_close_pnl(
    size_before: Any,
    entry_quote: Any,
    fill_size: Any,
    fill_price: Any,
    is_buy: bool,
) -> float:
    """Realized PnL from reducing a position; 0 when the fill adds."""
    pos = to_float(size_before)
    quote = to_float(entry_quote)
    fill = to_float(fill_size)
    px = to_float(fill_price)
    if pos == 0 or fill <= 0 or px <= 0:
        return 0.0
    reducing = (pos > 0 and not is_buy) or (pos < 0 and is_buy)
    if not reducing:
        return 0.0
    avg = abs(quote / pos)
    closed = min(fill, abs(pos))
    if pos > 0:
        return (px - avg) * closed
    return (avg - px) * closed


def desk_account_trade(raw: Any, account_index: int) -> dict[str, Any] | None:
    size = str(g(raw, "size", "0") or "0")
    if to_float(size) <= 0:
        return None
    mi = int(g(raw, "market_id", g(raw, "market_index", 0)) or 0)
    meta = gateway.get_market_by_index(mi)
    symbol = str(g(raw, "symbol", "") or (meta.symbol if meta else str(mi)))
    bid_acct = int(g(raw, "bid_account_id", 0) or 0)
    ask_acct = int(g(raw, "ask_account_id", 0) or 0)
    is_maker_ask = bool(g(raw, "is_maker_ask", False))
    if bid_acct == account_index:
        side = "buy"
        is_maker = not is_maker_ask
    elif ask_acct == account_index:
        side = "sell"
        is_maker = is_maker_ask
    else:
        return None
    is_buy = side == "buy"
    pnl = _nonzero_amount(g(raw, "bid_account_pnl" if is_buy else "ask_account_pnl", None))
    if pnl is None:
        pnl = _nonzero_amount(g(raw, "ask_account_pnl" if is_buy else "bid_account_pnl", None))
    if pnl is None:
        prefix = "maker" if is_maker else "taker"
        reconstructed = realized_close_pnl(
            g(raw, f"{prefix}_position_size_before", 0),
            g(raw, f"{prefix}_entry_quote_before", 0),
            size,
            g(raw, "price", 0),
            is_buy,
        )
        pnl = str(reconstructed)
    fee = str(g(raw, "maker_fee" if is_maker else "taker_fee", "0") or "0")
    return {
        "trade_id": str(g(raw, "trade_id", 0) or 0),
        "market_index": mi,
        "symbol": symbol,
        "side": side,
        "is_maker": is_maker,
        "price": str(g(raw, "price", "0") or "0"),
        "size": size,
        "usd_amount": str(g(raw, "usd_amount", "0") or "0"),
        "fee": fee,
        "pnl": pnl,
        "type": str(g(raw, "type", "trade") or "trade"),
        "timestamp": int(g(raw, "timestamp", g(raw, "transaction_time", 0)) or 0),
        "ask_id": int(g(raw, "ask_id", 0) or 0),
        "bid_id": int(g(raw, "bid_id", 0) or 0),
        "ask_client_id": int(g(raw, "ask_client_id", 0) or 0),
        "bid_client_id": int(g(raw, "bid_client_id", 0) or 0),
        "ask_account_id": ask_acct,
        "bid_account_id": bid_acct,
    }


def public_trade(raw: dict[str, Any]) -> dict[str, Any] | None:
    account_index = settings.lighter_account_index
    if account_index:
        desk = desk_account_trade(raw, account_index)
        if desk:
            return desk
    size = str(g(raw, "size", "0") or "0")
    if to_float(size) <= 0:
        return None
    return {
        "trade_id": str(g(raw, "trade_id", 0) or 0),
        "market_index": int(g(raw, "market_id", g(raw, "market_index", 0)) or 0),
        "size": size,
        "price": str(g(raw, "price", "0") or "0"),
        "ask_id": int(g(raw, "ask_id", 0) or 0),
        "bid_id": int(g(raw, "bid_id", 0) or 0),
        "ask_client_id": int(g(raw, "ask_client_id", 0) or 0),
        "bid_client_id": int(g(raw, "bid_client_id", 0) or 0),
        "ask_account_id": int(g(raw, "ask_account_id", 0) or 0),
        "bid_account_id": int(g(raw, "bid_account_id", 0) or 0),
        "timestamp": int(g(raw, "timestamp", g(raw, "transaction_time", 0)) or 0),
    }


def desk_position_funding(raw: Any) -> dict[str, Any]:
    mi = int(g(raw, "market_id", g(raw, "market_index", 0)) or 0)
    meta = gateway.get_market_by_index(mi)
    symbol = str(g(raw, "symbol", "") or (meta.symbol if meta else str(mi)))
    return {
        "funding_id": int(g(raw, "funding_id", 0) or 0),
        "market_index": mi,
        "symbol": symbol,
        "side": str(g(raw, "position_side", "long") or "long"),
        "position_size": str(g(raw, "position_size", "0") or "0"),
        "rate": str(g(raw, "rate", "0") or "0"),
        "change": str(g(raw, "change", "0") or "0"),
        "discount": str(g(raw, "discount", "0") or "0"),
        "timestamp": int(g(raw, "timestamp", 0) or 0),
    }


def position_items(raw: Any) -> list[tuple[int, Any]]:
    pairs: list[tuple[int, Any]] = []
    if isinstance(raw, dict):
        seq = raw.items()
    elif isinstance(raw, list):
        seq = enumerate(raw)
    else:
        return pairs
    for key, item in seq:
        try:
            mi = int(g(item, "market_id", g(item, "market_index", key)) or key)
        except (TypeError, ValueError):
            continue
        pairs.append((mi, item))
    return pairs


def merge_positions(existing: list[Position], raw: Any, *, snapshot: bool) -> list[Position]:
    by_mi: dict[int, Position] = {} if snapshot else {p.market_index: p for p in existing}
    for mi, item in position_items(raw):
        pos = parse_position(item)
        if pos:
            by_mi[mi] = pos
        else:
            by_mi.pop(mi, None)
    return list(by_mi.values())


def _raw_order_index(raw: Any) -> int:
    try:
        return int(g(raw, "order_index", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _order_market_index(raw: Any, fallback: int = 0) -> int:
    try:
        return int(g(raw, "market_index", g(raw, "market_id", fallback)) or fallback)
    except (TypeError, ValueError):
        return fallback


def incoming_orders_by_market(raw: Any) -> dict[int, list[Any]]:
    """Normalize REST lists and WS {market_id: [orders]} payloads."""
    grouped: dict[int, list[Any]] = {}
    if raw is None:
        return grouped
    if not isinstance(raw, list | dict):
        nested = g(raw, "orders", None)
        if nested is not None:
            raw = nested
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        nested = raw.get("orders")
        if nested is not None and not any(
            k in raw for k in ("order_index", "client_order_index")
        ):
            return incoming_orders_by_market(nested)
        if any(k in raw for k in ("order_index", "client_order_index", "price")):
            items = [raw]
        else:
            for key, orders in raw.items():
                try:
                    mi = int(key)
                except (TypeError, ValueError):
                    continue
                rows = orders if isinstance(orders, list) else [orders]
                grouped.setdefault(mi, []).extend(rows)
            return grouped
    else:
        items = [raw]
    for item in items:
        mi = _order_market_index(item)
        grouped.setdefault(mi, []).append(item)
    return grouped


def apply_orders(
    existing: dict[int, list[OpenOrder]], raw: Any, *, snapshot: bool
) -> dict[int, list[OpenOrder]]:
    # Subscribe is a full book. Incremental updates are deltas: upsert still-open
    # orders, drop canceled/filled ones, leave unmentioned siblings alone.
    incoming = incoming_orders_by_market(raw)
    if snapshot:
        by_index: dict[int, dict[int, OpenOrder]] = {}
    else:
        by_index = {mi: {o.order_index: o for o in rows} for mi, rows in existing.items()}
    for mi, rows in incoming.items():
        current = {} if snapshot else dict(by_index.get(mi, {}))
        for item in rows:
            parsed = parse_order(item)
            if parsed:
                current[parsed.order_index] = parsed
                continue
            idx = _raw_order_index(item)
            if idx:
                current.pop(idx, None)
        if current:
            by_index[mi] = current
        else:
            by_index.pop(mi, None)
    return {mi: list(rows.values()) for mi, rows in by_index.items()}


def asset_rows(assets: Any) -> list[dict[str, Any]]:
    if not assets:
        return []
    if isinstance(assets, dict):
        items = list(assets.values())
    elif isinstance(assets, list):
        items = assets
    else:
        return []
    out: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            row = dict(item)
        else:
            row = {
                "symbol": getattr(item, "symbol", None),
                "asset_id": getattr(item, "asset_id", None),
                "balance": getattr(item, "balance", None),
                "locked_balance": getattr(item, "locked_balance", None),
                "margin_balance": getattr(item, "margin_balance", None),
                "margin_mode": getattr(item, "margin_mode", None),
                "multiplier": getattr(item, "multiplier", None),
            }
        sym = str(row.get("symbol") or "").upper()
        if not sym:
            continue
        row["symbol"] = sym
        out.append(row)
    return out


def merge_account_assets(prev: Any, incoming: Any) -> list[dict[str, Any]]:
    """Field-wise merge so a WS balance tick does not drop REST margin_mode."""
    old_rows = {r["symbol"]: r for r in asset_rows(prev)}
    new_rows = {r["symbol"]: r for r in asset_rows(incoming)}
    if not new_rows:
        return list(old_rows.values())
    merged = dict(old_rows)
    for sym, row in new_rows.items():
        prev_row = merged.get(sym, {})
        combined = dict(prev_row)
        for key, value in row.items():
            if value is None or value == "":
                continue
            combined[key] = value
        merged[sym] = combined
    return list(merged.values())
