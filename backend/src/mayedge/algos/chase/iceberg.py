from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from enum import StrEnum
from typing import Literal

ALGO_ID = "chase-iceberg"
ALGO_VERSION = "1"
BPS = Decimal("10000")

Side = Literal["buy", "sell"]


class Action(StrEnum):
    REST = "rest"
    PAUSE = "pause"
    DONE = "done"


@dataclass(frozen=True)
class ChaseIcebergParams:
    """Stable names. offset_bps: 4 = 0.04%."""

    side: Side
    qty: Decimal
    display_qty: Decimal
    offset_bps: Decimal
    price_floor: Decimal
    price_ceiling: Decimal


@dataclass(frozen=True)
class MarketView:
    bid: Decimal | None
    ask: Decimal | None
    tick: Decimal
    min_qty: Decimal
    qty_step: Decimal = Decimal("0")


@dataclass(frozen=True)
class Quote:
    action: Action
    price: Decimal | None = None
    qty: Decimal | None = None
    reason: str | None = None


def round_passive(price: Decimal, tick: Decimal, side: Side) -> Decimal:
    """Tick-round away from the spread. Buy down, sell up."""
    if tick <= 0:
        raise ValueError("tick must be positive")
    steps = price / tick
    if side == "buy":
        n = steps.to_integral_value(rounding=ROUND_DOWN)
    else:
        n = steps.to_integral_value(rounding=ROUND_UP)
    return n * tick


def _clip_qty(remaining: Decimal, display_qty: Decimal, step: Decimal) -> Decimal:
    clip = remaining if remaining <= display_qty else display_qty
    if step > 0:
        n = (clip / step).to_integral_value(rounding=ROUND_DOWN)
        clip = n * step
    return clip


def leftover_is_dust(remaining: Decimal, min_qty: Decimal) -> bool:
    """Leftover cannot rest at venue min size — drop it, do not invent-fill."""
    return min_qty > 0 and remaining > 0 and remaining < min_qty


def decide(
    params: ChaseIcebergParams,
    market: MarketView,
    remaining: Decimal,
) -> Quote:
    """Next passive clip, or Pause/Done. Never crosses the spread.

    Buy: park behind the bid by offset_bps; do not work below floor;
    if bid is above ceiling, rest at ceiling only when that is still
    strictly below the ask.

    Sell: park behind the ask; do not work above ceiling; if ask is
    below floor, rest at floor only when that is still strictly above
    the bid.

    remaining < min_qty → Pause (cannot work below min qty).
    Last clip uses remaining when it is ≤ display_qty.
    """
    if remaining <= 0:
        return Quote(Action.DONE, reason="filled")

    clip = _clip_qty(remaining, params.display_qty, market.qty_step)
    if clip < market.min_qty:
        return Quote(Action.PAUSE, reason="below_min_qty")

    bid = market.bid
    ask = market.ask
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return Quote(Action.PAUSE, reason="no_book")

    tick = market.tick
    floor = params.price_floor
    ceiling = params.price_ceiling
    if floor >= ceiling:
        return Quote(Action.PAUSE, reason="invalid_band")

    offset = params.offset_bps / BPS
    if offset < 0:
        return Quote(Action.PAUSE, reason="invalid_offset")

    if params.side == "buy":
        if bid < floor:
            return Quote(Action.PAUSE, reason="below_floor")
        if bid > ceiling:
            px = round_passive(ceiling, tick, "buy")
        else:
            px = round_passive(bid * (1 - offset), tick, "buy")
            if px > ceiling:
                px = round_passive(ceiling, tick, "buy")
        if px < floor:
            return Quote(Action.PAUSE, reason="below_floor")
        if px >= ask:
            return Quote(Action.PAUSE, reason="would_cross")
        return Quote(Action.REST, price=px, qty=clip)

    if ask > ceiling:
        return Quote(Action.PAUSE, reason="above_ceiling")
    if ask < floor:
        px = round_passive(floor, tick, "sell")
    else:
        px = round_passive(ask * (1 + offset), tick, "sell")
        if px < floor:
            px = round_passive(floor, tick, "sell")
    if px > ceiling:
        return Quote(Action.PAUSE, reason="above_ceiling")
    if px <= bid:
        return Quote(Action.PAUSE, reason="would_cross")
    return Quote(Action.REST, price=px, qty=clip)
