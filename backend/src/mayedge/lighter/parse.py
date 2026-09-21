from __future__ import annotations

from decimal import Decimal
from typing import Any

from mayedge.config import settings
from mayedge.lighter.gateway import gateway
from mayedge.lighter.models import Asset, OpenOrder, Position, imf_to_leverage, to_float
from mayedge.numbers import fmt_decimal, parse_decimal


def g(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _is_stop_take_type(order_type: str) -> bool:
    t = order_type.lower().replace("_", "").replace("-", "").replace(" ", "")
    if t in {"2", "3", "4", "5"}:
        return True
    return "stoploss" in t or "takeprofit" in t


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
    order_type = str(g(raw, "type", g(raw, "order_type", "limit")) or "limit")
    trigger_price = str(g(raw, "trigger_price", g(raw, "triggerPrice", "")) or "")
    pending_parent = to_float(trigger_price) > 0 or _is_stop_take_type(order_type)
    if to_float(remaining) <= 0 and not pending_parent:
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
        order_type=order_type,
        reduce_only=bool(g(raw, "reduce_only", False)),
        trigger_price=trigger_price,
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


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(str(value)))
        except (TypeError, ValueError):
            return default


def desk_position_funding(raw: Any) -> dict[str, Any]:
    mi = _as_int(g(raw, "market_id", g(raw, "market_index", 0)))
    meta = gateway.get_market_by_index(mi)
    symbol = str(g(raw, "symbol", "") or (meta.symbol if meta else str(mi)))
    side_raw = str(g(raw, "position_side", g(raw, "side", "long")) or "long").lower()
    return {
        "funding_id": _as_int(g(raw, "funding_id", 0)),
        "market_index": mi,
        "symbol": symbol,
        "side": "short" if side_raw.startswith("short") else "long",
        "position_size": str(g(raw, "position_size", "0") or "0"),
        "rate": str(g(raw, "rate", "0") or "0"),
        "change": str(g(raw, "change", "0") or "0"),
        "discount": str(g(raw, "discount", "0") or "0"),
        "timestamp": _as_int(g(raw, "timestamp", 0)),
    }


def parse_position_fundings_page(payload: Any) -> dict[str, Any]:
    """Desk shape for GET /api/v1/positionFunding, skipping the SDK models."""
    if not isinstance(payload, dict):
        return {"fundings": [], "next_cursor": None}
    fundings: list[dict[str, Any]] = []
    for row in payload.get("position_fundings") or []:
        try:
            fundings.append(desk_position_funding(row))
        except (TypeError, ValueError):
            continue
    cursor = payload.get("next_cursor")
    next_cursor = None if cursor in (None, "") else str(cursor)
    return {"fundings": fundings, "next_cursor": next_cursor}


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
        if nested is not None and not any(k in raw for k in ("order_index", "client_order_index")):
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


_QUOTE = frozenset({"USDC", "USDG"})
_DUST_USD = 0.01


def _num_str(value: Any) -> str:
    if value is None or value == "":
        return "0"
    if isinstance(value, str):
        return value
    if isinstance(value, Decimal):
        return fmt_decimal(value) or "0"
    return fmt_decimal(Decimal(str(value))) or "0"


def _qty(row: dict[str, Any], key: str) -> Decimal:
    raw = row.get(key)
    if raw in (None, ""):
        return Decimal("0")
    try:
        return abs(parse_decimal(raw))
    except ValueError:
        return Decimal("0")


def asset_holding_qty(row: dict[str, Any]) -> float:
    """Spot balance, perp collateral, or locked size — any of them is a holding."""
    return float(
        max(_qty(row, "balance"), _qty(row, "margin_balance"), _qty(row, "locked_balance"))
    )


def _avg_entry(row: dict[str, Any], entries: dict[Any, Any] | None) -> Decimal | None:
    if not entries:
        return None
    aid = row.get("asset_id")
    keys: list[Any] = []
    if aid not in (None, ""):
        try:
            keys.append(int(aid))
        except (TypeError, ValueError):
            pass
        keys.append(str(aid))
        keys.append(aid)
    for key in keys:
        raw = entries.get(key)
        if isinstance(raw, dict):
            raw = raw.get("avg_entry_price")
        if raw in (None, ""):
            continue
        try:
            price = parse_decimal(raw)
        except ValueError:
            continue
        if price > 0:
            return price
    return None


def public_assets(
    assets: Any,
    details: dict[str, dict[str, float]] | None = None,
    entries: dict[Any, Any] | None = None,
) -> list[Asset]:
    """Project venue holdings + assetDetails into public Asset rows.

    Spot ``balance`` and perp ``margin_balance`` are disjoint buckets.
    Balance is total owned; Asset available is total minus spot locks.
    Asset uPnL is (index − avg entry) × total; quote has none.
    """
    meta = details or {}
    out: list[Asset] = []
    for row in asset_rows(assets):
        spot = _qty(row, "balance")
        margin_qty = _qty(row, "margin_balance")
        locked = _qty(row, "locked_balance")
        total = spot + margin_qty
        if total == 0 and locked == 0:
            continue
        sym = str(row["symbol"]).upper()
        detail = meta.get(sym) or {}
        index = to_float(detail.get("index_price"))
        ltv = to_float(detail.get("loan_to_value"))
        if sym in _QUOTE:
            if index <= 0:
                index = 1.0
            if ltv <= 0:
                ltv = 1.0
        usd_val = float(total) * index if index > 0 else 0.0
        if index > 0 and usd_val < _DUST_USD:
            continue
        venue_available = row.get("available_balance")
        if venue_available not in (None, ""):
            available = str(venue_available)
        else:
            available = _num_str(max(Decimal("0"), total - locked))
        margin = row.get("margin_balance")
        pnl = ""
        if sym not in _QUOTE and index > 0:
            entry = _avg_entry(row, entries)
            if entry is not None:
                pnl = _num_str((Decimal(str(index)) - entry) * total)
        out.append(
            Asset(
                symbol=sym,
                balance=_num_str(total),
                margin_balance=_num_str(margin) if margin not in (None, "") else "0",
                available=available,
                index_price=_num_str(index),
                ltv=_num_str(ltv),
                usd=_num_str(usd_val) if index > 0 else "0",
                unrealized_pnl=pnl,
            )
        )
    return out


def merge_spot_entries(prev: dict[int, str] | None, incoming: Any) -> dict[int, str]:
    """asset_id → avg_entry_price from Lighter ``avg_entry_prices`` snapshots."""
    out = dict(prev or {})
    if isinstance(incoming, dict) and "avg_entry_prices" in incoming:
        incoming = incoming.get("avg_entry_prices")
    if isinstance(incoming, dict):
        items = incoming.values()
    elif isinstance(incoming, list):
        items = incoming
    else:
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        aid = item.get("asset_id")
        price = item.get("avg_entry_price")
        if aid in (None, "") or price in (None, ""):
            continue
        try:
            out[int(aid)] = str(price)
        except (TypeError, ValueError):
            continue
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
