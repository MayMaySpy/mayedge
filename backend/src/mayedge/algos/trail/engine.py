"""Trail math. Pure: no venue, no clock but the one passed in. Rule ids are docs/trail-rules.md.

A Trail's ``side`` is the side of the order it fires: the closing side for a Stop or
a Take Profit, the order's own side for an Entry. A sell fires on a fall, so it
follows the high; a buy fires on a rise, so it follows the low. That one sign covers
a long exit, a short exit, a long entry and a short entry alike (F1, F2).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Literal

from mayedge.algos.trail.config import MIN_GAP_MS, STEP_MIN_TICKS, STEP_SHARE

Side = Literal["buy", "sell"]
DistanceKind = Literal["pct", "price"]

HUNDRED = Decimal("100")


def favour(side: Side) -> int:
    """+1 when the best price is the highest, −1 when it is the lowest."""
    return 1 if side == "sell" else -1


@dataclass(frozen=True)
class Follow:
    side: Side
    distance: Decimal
    distance_kind: DistanceKind
    tick: Decimal
    activation: Decimal | None = None
    # The trigger is never worse than this: a Stop's start price (TS2).
    floor: Decimal | None = None


@dataclass(frozen=True)
class Point:
    """Where a Trail is. ``trigger`` is the desk's, not the venue order's."""

    active: bool = False
    best: Decimal | None = None
    trigger: Decimal | None = None


def offset(f: Follow, best: Decimal) -> Decimal:
    if f.distance_kind == "pct":
        return best * f.distance / HUNDRED
    return f.distance


def round_away(f: Follow, price: Decimal) -> Decimal:
    """F3: to the tick, away from the best price."""
    if f.tick <= 0:
        return price
    rounding = ROUND_FLOOR if favour(f.side) > 0 else ROUND_CEILING
    return (price / f.tick).to_integral_value(rounding=rounding) * f.tick


def trigger_at(f: Follow, best: Decimal) -> Decimal:
    """F2: the distance behind the best price."""
    return round_away(f, best - favour(f.side) * offset(f, best))


def better(f: Follow, a: Decimal, b: Decimal) -> bool:
    """``a`` is on the better side of ``b`` for this Trail."""
    return favour(f.side) * (a - b) > 0


def furthest(f: Follow, *prices: Decimal | None) -> Decimal | None:
    out: Decimal | None = None
    for p in prices:
        if p is not None and (out is None or better(f, p, out)):
            out = p
    return out


def reached(f: Follow, price: Decimal, level: Decimal) -> bool:
    """F5: price is at the level or past it on the favourable side."""
    return favour(f.side) * (price - level) >= 0


def crossed(f: Follow, trigger: Decimal, price: Decimal) -> bool:
    """Price has come back through the trigger: the Trail fires."""
    return favour(f.side) * (price - trigger) <= 0


def follow(f: Follow, point: Point, price: Decimal) -> Point:
    """F1–F5: take one price. The trigger only ever moves to the better side (F4)."""
    if price <= 0:
        return point
    if not point.active:
        if f.activation is not None and not reached(f, price, f.activation):
            return replace(point, trigger=furthest(f, point.trigger, f.floor))
        point = replace(point, active=True, best=price)
    best = point.best if point.best is not None and not better(f, price, point.best) else price
    trigger = furthest(f, trigger_at(f, best), point.trigger, f.floor)
    return Point(active=True, best=best, trigger=trigger)


def step(f: Follow, best: Decimal) -> Decimal:
    """F6: how far a venue order must improve before it is moved."""
    share = offset(f, best) * Decimal(STEP_SHARE)
    return max(share, f.tick * STEP_MIN_TICKS)


def backstop(f: Follow, trigger: Decimal, best: Decimal) -> Decimal:
    """L2: one step behind the trigger."""
    return round_away(f, trigger - favour(f.side) * step(f, best))


def move_due(
    f: Follow,
    *,
    venue: Decimal,
    wanted: Decimal,
    best: Decimal,
    now_ms: int,
    last_move_ms: int | None,
) -> bool:
    """F6: the venue order moves only by a step, and only after the min gap."""
    if not better(f, wanted, venue):
        return False
    if favour(f.side) * (wanted - venue) < step(f, best):
        return False
    return last_move_ms is None or now_ms - last_move_ms >= MIN_GAP_MS
