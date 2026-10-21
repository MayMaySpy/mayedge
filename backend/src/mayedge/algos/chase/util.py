"""Shared helpers for chase runner modules."""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

from mayedge.lighter.errors import (
    is_blocked,
    is_invalid_nonce,
    is_min_size,
    is_order_not_found,
    is_would_cross,
)
from mayedge.numbers import fmt_decimal


def now_ms() -> int:
    """Wall clock still used by algos that have not moved to ``common.now_ms``."""
    return int(time.time() * 1000)


def _fmt(d: Decimal | None) -> str | None:
    return fmt_decimal(d)


def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


def _is_rate_limit(err: BaseException) -> bool:
    return is_blocked(err)


def _is_order_not_found(err: BaseException) -> bool:
    return is_order_not_found(err)


def _is_min_size(err: BaseException) -> bool:
    return is_min_size(err)


def _is_would_cross(err: BaseException) -> bool:
    return is_would_cross(err)


def _is_invalid_nonce(err: BaseException | str | None) -> bool:
    return is_invalid_nonce(err)
