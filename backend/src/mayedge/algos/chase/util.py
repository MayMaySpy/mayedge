"""Shared helpers for chase runner modules."""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

from mayedge.algos.chase.config import CHASE_COI_BASE, CHASE_COI_END
from mayedge.lighter.errors import Reject, reject_reason
from mayedge.numbers import fmt_decimal
from mayedge.rows import is_obj


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
    for o in orders or ():
        if is_obj(o):
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
    return reject_reason(err) is Reject.BLOCKED


def _is_order_not_found(err: BaseException) -> bool:
    return reject_reason(err) is Reject.ORDER_NOT_FOUND


def _is_min_size(err: BaseException) -> bool:
    return reject_reason(err) is Reject.MIN_SIZE


def _is_would_cross(err: BaseException) -> bool:
    return reject_reason(err) is Reject.WOULD_CROSS


def _is_invalid_nonce(err: BaseException | str | None) -> bool:
    return reject_reason(err) is Reject.INVALID_NONCE
