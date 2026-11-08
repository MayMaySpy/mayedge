"""MS21, MS23: the ATR an ATR-Step Massager follows, and the last close it checks against
its Band. Pure: candles in, numbers out."""

from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import Decimal

from mayedge.algos.massager.config import TIMEFRAME_MS
from mayedge.algos.massager.plan import ATR_LENGTH
from mayedge.lighter.models import Candle
from mayedge.mayrekt import atr


def closed_atr(
    candles: Sequence[Candle], timeframe: str, now_ms: int, length: int = ATR_LENGTH
) -> Decimal | None:
    """ATR(length) on the candles that have closed by ``now_ms``. None without enough."""
    period = TIMEFRAME_MS.get(timeframe, 3_600_000)
    closed = [c for c in candles if c.time * 1000 + period <= now_ms]
    if len(closed) < length:
        return None
    values = atr(
        [c.high for c in closed], [c.low for c in closed], [c.close for c in closed], length
    )
    last = values[-1]
    if not math.isfinite(last) or last <= 0:
        return None
    return Decimal(repr(last))


def last_close(
    candles: Sequence[Candle], timeframe: str, now_ms: int
) -> tuple[int, Decimal] | None:
    """MS23: the newest candle closed by ``now_ms``, as (its close time in ms, its close)."""
    period = TIMEFRAME_MS.get(timeframe, 3_600_000)
    closed = [c for c in candles if c.time * 1000 + period <= now_ms]
    if not closed:
        return None
    last = max(closed, key=lambda c: c.time)
    if not math.isfinite(last.close) or last.close <= 0:
        return None
    return last.time * 1000 + period, Decimal(repr(last.close))
