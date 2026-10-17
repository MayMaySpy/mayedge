"""What Planner reads from the venue, through the execution port."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from mayedge.algos.chase.execution import ChaseExecution
from mayedge.algos.planner.plan import MarketContext
from mayedge.lighter.coi import is_algo_client_order
from mayedge.lighter.models import maker_min_base
from mayedge.lighter.orders import protect_role_kind


def dec(raw: object) -> Decimal | None:
    if raw is None or raw == "":
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None


@dataclass(frozen=True)
class HeldPosition:
    size: Decimal  # signed: + long, − short
    entry: Decimal | None
    liq_price: Decimal | None


def _payload(ex: ChaseExecution) -> dict[str, Any]:
    return ex.cached_account_payload() or {}


def position(ex: ChaseExecution, market_index: int) -> HeldPosition:
    for raw in _payload(ex).get("positions") or []:
        if not isinstance(raw, dict) or int(raw.get("market_index") or -1) != market_index:
            continue
        size = dec(raw.get("size")) or Decimal("0")
        entry = dec(raw.get("entry_price"))
        liq = dec(raw.get("liquidation_price"))
        return HeldPosition(
            size=size,
            entry=entry if entry and entry > 0 else None,
            liq_price=liq if liq and liq > 0 else None,
        )
    return HeldPosition(size=Decimal("0"), entry=None, liq_price=None)


def open_orders(ex: ChaseExecution) -> list[dict[str, Any]]:
    return [o for o in _payload(ex).get("open_orders") or [] if isinstance(o, dict)]


def ticket_protects(ex: ChaseExecution, market_index: int) -> list[dict[str, Any]]:
    """S6: the Stop and Take Profit Tickets Attach replaces."""
    out: list[dict[str, Any]] = []
    for o in open_orders(ex):
        if int(o.get("market_index") or -1) != market_index:
            continue
        if is_algo_client_order(int(o.get("client_order_index") or 0)):
            continue
        if protect_role_kind(str(o.get("order_type") or "")) is None:
            continue
        out.append(o)
    return out


def market_context(ex: ChaseExecution, market_index: int) -> tuple[MarketContext, str]:
    """The numbers a plan is drawn from, and the Market's symbol."""
    meta = ex.get_market_by_index(market_index)
    if not meta:
        raise ValueError("Unknown market")
    tick = Decimal(10) ** -meta.price_decimals
    qty_step = Decimal(10) ** -meta.size_decimals
    mark = dec(meta.mark_price) or dec(meta.last_trade_price) or Decimal("0")
    min_qty = maker_min_base(
        meta.min_base_amount,
        meta.min_quote_amount,
        mark if mark > 0 else None,
        qty_step,
    )
    payload = _payload(ex)
    held = position(ex, market_index)
    equity = dec(payload.get("portfolio_margin"))
    ctx = MarketContext(
        tick=tick,
        qty_step=qty_step,
        min_qty=min_qty if min_qty > 0 else qty_step,
        mark=mark,
        equity=equity if equity and equity > 0 else None,
        taker_bps=dec(payload.get("taker_fee_bps")) or Decimal("0"),
        liq_price=held.liq_price,
        position_size=held.size,
        position_entry=held.entry,
    )
    return ctx, str(meta.symbol)
