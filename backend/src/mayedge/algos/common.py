"""Helpers shared by every algo. Patch ``now_ms`` on this module in tests."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from mayedge.rows import is_obj


def now_ms() -> int:
    return int(time.time() * 1000)


def in_coi_range(coi: int | None, base: int, end: int) -> bool:
    return coi is not None and base <= coi < end


def venue_order_keys(
    orders: Any,
    accept: Callable[[int], bool],
    *,
    keep_unindexed: bool = False,
) -> list[tuple[int, int]]:
    """``(market_index, order_index)`` for rows ``accept`` keeps.

    ``keep_unindexed`` stores a missing order index as the client order index.
    Chase and ladder drop those rows; grid keeps them.
    """
    keys: list[tuple[int, int]] = []
    for raw in orders or ():
        if raw is None:
            continue
        if is_obj(raw):
            coi = int(raw.get("client_order_index") or 0)
            mi = int(raw.get("market_index") or 0)
            idx = int(raw.get("order_index") or 0)
        else:
            coi = int(getattr(raw, "client_order_index", 0) or 0)
            mi = int(getattr(raw, "market_index", 0) or 0)
            idx = int(getattr(raw, "order_index", 0) or 0)
        if not accept(coi):
            continue
        if not idx and not keep_unindexed:
            continue
        keys.append((mi, idx or coi) if keep_unindexed else (mi, idx))
    return keys
