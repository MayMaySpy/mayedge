"""Shared helpers for chase-grid."""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

from mayedge.numbers import fmt_decimal, parse_decimal


def now_ms() -> int:
    return int(time.time() * 1000)


def _dec(raw: object) -> Decimal:
    if isinstance(raw, Decimal):
        return raw
    if raw is None:
        return Decimal("0")
    return parse_decimal(str(raw)) or Decimal("0")


def _fmt(d: Decimal | None) -> str | None:
    return fmt_decimal(d)


def _grid_order_keys(orders: Any, cois: set[int]) -> list[tuple[int, int]]:
    keys: list[tuple[int, int]] = []
    for raw in orders or []:
        if raw is None:
            continue
        if isinstance(raw, dict):
            coi = int(raw.get("client_order_index") or 0)
            mi = int(raw.get("market_index") or 0)
            oid = int(raw.get("order_index") or 0)
        else:
            coi = int(getattr(raw, "client_order_index", 0) or 0)
            mi = int(getattr(raw, "market_index", 0) or 0)
            oid = int(getattr(raw, "order_index", 0) or 0)
        if coi in cois:
            keys.append((mi, oid or coi))
    return keys
