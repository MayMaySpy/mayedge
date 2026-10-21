"""A Round trip's Excursion: how far price went against it (MAE) and for it (MFE) while open.

Measured from the trip's average entry over the candles that cover its span, at the
smallest bar size that fits one read. The first and last bars can reach a little before
the entry or after the exit, so both numbers are bounds at that bar size.
The rules are docs/journal-rules.md, Excursion.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from mayedge.lighter.models import Candle

# Bar sizes the venue serves, smallest first.
RESOLUTIONS: tuple[tuple[str, int], ...] = (
    ("1m", 60),
    ("5m", 300),
    ("15m", 900),
    ("1h", 3600),
    ("4h", 14_400),
    ("1d", 86_400),
)
MAX_BARS = 500


def resolution_for(open_ts: int, close_ts: int) -> tuple[str, int, int]:
    """The smallest bar size whose bars over the span fit one read: (name, seconds, count)."""
    span = max(0, close_ts - open_ts)
    for name, step in RESOLUTIONS:
        count = span // step + 2
        if count <= MAX_BARS:
            return name, step, count
    name, step = RESOLUTIONS[-1]
    return name, step, MAX_BARS


@dataclass(frozen=True)
class Excursion:
    resolution: str
    # Percent of the average entry; MAE is zero or less, MFE zero or more.
    mae_pct: Decimal
    mfe_pct: Decimal
    # The same moves times the trip's size, in USD.
    mae_usd: Decimal
    mfe_usd: Decimal


def excursion(
    side: str,
    avg_in: Decimal,
    size: Decimal,
    candles: list[Candle],
    open_ts: int,
    close_ts: int,
    resolution: str,
    step: int,
) -> Excursion | None:
    """MAE and MFE over the bars that overlap [open_ts, close_ts]; None without a bar or an entry."""
    bars = [c for c in candles if c.time + step > open_ts and c.time <= close_ts]
    if not bars or avg_in <= 0:
        return None
    high = Decimal(str(max(c.high for c in bars)))
    low = Decimal(str(min(c.low for c in bars)))
    if side == "long":
        best, worst = high - avg_in, low - avg_in
    else:
        best, worst = avg_in - low, avg_in - high
    best, worst = max(best, Decimal(0)), min(worst, Decimal(0))
    qty = abs(size)
    hundred = Decimal(100)
    return Excursion(
        resolution=resolution,
        mae_pct=worst / avg_in * hundred,
        mfe_pct=best / avg_in * hundred,
        mae_usd=worst * qty,
        mfe_usd=best * qty,
    )
