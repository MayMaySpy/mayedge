"""MS21: the ATR an ATR-Step Massager follows. Pure: candles in, a price out."""

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
