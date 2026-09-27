from __future__ import annotations

from decimal import Decimal
from typing import Any

from mayedge.lighter.models import to_float
from mayedge.numbers import fmt_decimal

_QUOTE = frozenset({"USDC", "USDG"})


def _rows(assets: Any) -> list[dict[str, Any]]:
    if not assets:
        return []
    if isinstance(assets, dict):
        items = list(assets.values())
    else:
        items = list(assets)
    out: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            row = item
        else:
            row = {
                "symbol": getattr(item, "symbol", None),
                "margin_balance": getattr(item, "margin_balance", None),
            }
        if str(row.get("symbol") or "").upper():
            out.append(row)
    return out


def portfolio_margin_usd(
    cross_portfolio: float,
    assets: Any,
    details: dict[str, dict[str, float]],
) -> float:
    """Lighter TAV: USDC portfolio + Σ LTV × margin_balance × index."""
    total = cross_portfolio
    for row in _rows(assets):
        sym = str(row.get("symbol") or "").upper()
        if sym in _QUOTE:
            continue
        meta = details.get(sym)
        if not meta:
            continue
        index = to_float(meta.get("index_price"))
        ltv = to_float(meta.get("loan_to_value"))
        qty = to_float(row.get("margin_balance"))
        if index <= 0 or qty == 0:
            continue
        total += ltv * qty * index
    return total


def liquidation_threshold_usd(
    assets: Any,
    details: dict[str, dict[str, float]],
) -> float:
    """Non-quote Margin balance at the Liquidation threshold, in USD.

    Quote is already inside the USDC portfolio. LTV is not this haircut.
    """
    total = 0.0
    for row in _rows(assets):
        sym = str(row.get("symbol") or "").upper()
        if sym in _QUOTE:
            continue
        meta = details.get(sym)
        if not meta:
            continue
        index = to_float(meta.get("index_price"))
        threshold = to_float(meta.get("liquidation_threshold"))
        qty = to_float(row.get("margin_balance"))
        if index <= 0 or threshold <= 0 or qty == 0:
            continue
        total += threshold * qty * index
    return total


def format_cross_liquidation_price(
    *,
    mark: float,
    size: float,
    maintenance_fraction: float,
    talt: float,
    mmr: float,
) -> str | None:
    """Price where TALT meets maintenance, other marks held fixed.

    None when the inputs cannot define a price. ``"0"`` when that price is
    not positive — the desk shows a blank.
    """
    if mark <= 0 or size == 0 or maintenance_fraction <= 0:
        return None
    mark_d = Decimal(str(mark))
    size_d = Decimal(str(size))
    mm_d = Decimal(str(maintenance_fraction))
    sign = Decimal(1 if size > 0 else -1)
    denom = abs(size_d) * (mm_d - sign)
    if denom == 0:
        return None
    liq = mark_d + (Decimal(str(talt)) - Decimal(str(mmr))) / denom
    if liq <= 0:
        return "0"
    return fmt_decimal(liq) or "0"


def trade_available_usd(
    available: float, portfolio_margin: float, cross_portfolio: float
) -> float:
    """Free margin for new orders: USDC available + LTV of non-quote collateral.

    Lighter ``available_balance`` is USDC-only. Order risk checks use TAV, so
    buying power must include the haircut already in ``portfolio_margin``.
    """
    asset_margin = max(0.0, portfolio_margin - max(cross_portfolio, 0.0))
    return max(0.0, available) + asset_margin
