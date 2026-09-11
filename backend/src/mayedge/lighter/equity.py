from __future__ import annotations

from typing import Any

from mayedge.lighter.models import to_float

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
