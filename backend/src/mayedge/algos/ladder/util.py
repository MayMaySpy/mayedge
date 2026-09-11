"""Shared helpers for ladder runner."""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

from mayedge.algos.ladder.config import LADDER_COI_BASE, LADDER_COI_END
from mayedge.numbers import fmt_decimal


def now_ms() -> int:
    return int(time.time() * 1000)


def _fmt(d: Decimal | None) -> str | None:
    return fmt_decimal(d)


def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


def is_ladder_client_order(coi: int | None) -> bool:
    return coi is not None and LADDER_COI_BASE <= coi < LADDER_COI_END


def _ladder_order_keys(orders: Any, cois: set[int] | None = None) -> list[tuple[int, int]]:
    keys: list[tuple[int, int]] = []
    for o in orders or []:
        if isinstance(o, dict):
            coi = int(o.get("client_order_index") or 0)
            mi = int(o.get("market_index") or 0)
            idx = int(o.get("order_index") or 0)
        else:
            coi = int(getattr(o, "client_order_index", 0) or 0)
            mi = int(getattr(o, "market_index", 0) or 0)
            idx = int(getattr(o, "order_index", 0) or 0)
        if not idx or not is_ladder_client_order(coi):
            continue
        if cois is not None and coi not in cois:
            continue
        keys.append((mi, idx))
    return keys
