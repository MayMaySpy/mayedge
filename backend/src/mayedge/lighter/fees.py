"""Lighter fee ticks → bps. 1 tick = 1 / 1e6 of notional (40 ticks = 0.40 bps)."""

from __future__ import annotations

from decimal import Decimal

FEE_TICK = Decimal("1000000")
BPS = Decimal("10000")


def ticks_to_bps(tick: int | None) -> Decimal:
    if not tick:
        return Decimal("0")
    return Decimal(int(tick)) * BPS / FEE_TICK


def cycle_bps(*, maker_bps: Decimal, taker_bps: Decimal, flatten_is_taker: bool) -> Decimal:
    """Round-trip fee in bps: maker+maker (TP) or maker+taker (market B/E)."""
    if flatten_is_taker:
        return maker_bps + taker_bps
    return maker_bps + maker_bps
