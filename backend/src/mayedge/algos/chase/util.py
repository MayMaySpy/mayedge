"""Shared helpers for chase runner modules."""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

from mayedge.algos.chase.config import CHASE_COI_BASE, CHASE_COI_END
from mayedge.numbers import fmt_decimal


def now_ms() -> int:
    """Wall clock for chase runner — patch in tests via chase_harness.patch_chase."""
    return int(time.time() * 1000)


def _fmt(d: Decimal | None) -> str | None:
    return fmt_decimal(d)


def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


def is_chase_client_order(coi: int | None) -> bool:
    return coi is not None and CHASE_COI_BASE <= coi < CHASE_COI_END


def _chase_order_keys(orders: Any, cois: set[int] | None = None) -> list[tuple[int, int]]:
    """(market_index, order_index) for venue children of this algo."""
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
        if not idx or not is_chase_client_order(coi):
            continue
        if cois is not None and coi not in cois:
            continue
        keys.append((mi, idx))
    return keys


def _is_rate_limit(err: BaseException) -> bool:
    text = str(err)
    return (
        "429" in text
        or "23000" in text
        or "too many requests" in text.lower()
        or "ratelimit" in text.lower()
    )


def _is_order_not_found(err: BaseException) -> bool:
    text = str(err).lower()
    return "order not found" in text or "21701" in text


def _is_min_size(err: BaseException) -> bool:
    text = str(err).lower()
    return "21706" in text or "min " in text or "base or quote amount" in text


def _is_invalid_nonce(err: BaseException | str | None) -> bool:
    text = str(err or "").lower()
    return "21104" in text or "invalid nonce" in text
