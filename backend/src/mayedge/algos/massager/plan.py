"""Massager planner. Pure: no venue, no clock. Rule ids are docs/massager-rules.md.

Sizes are signed: long above zero, short below. The Position is Core + Lean.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Literal

ALGO_ID = "massager"
ALGO_VERSION = "1"

Side = Literal["buy", "sell"]
Verdict = Literal["run", "pause", "stop"]

BPS = Decimal("10000")
ZERO = Decimal("0")
# MS9: levels resting on each side of the current one.
RESTING_EACH_SIDE = 2


class MassagerRefused(ValueError):
    """A Massager that breaks a rule. ``rule`` is its id in massager-rules.md."""

    def __init__(self, rule: str, message: str) -> None:
        super().__init__(message)
        self.rule = rule
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"rule": self.rule, "message": self.message}


@dataclass(frozen=True)
class MassagerParams:
    band_low: Decimal
    band_high: Decimal
    swing: Decimal
    clip: Decimal


@dataclass(frozen=True)
class Venue:
    """What the Market allows. ``maker_bps`` is the account's maker fee."""

    tick: Decimal
    size_step: Decimal
    min_qty: Decimal
    maker_bps: Decimal = ZERO


@dataclass(frozen=True)
class Lattice:
    """MS5: the Band cut into levels. ``prices[k + levels]`` is level k."""

    levels: int
    center: Decimal
    step: Decimal
    prices: tuple[Decimal, ...]

    def price(self, k: int) -> Decimal:
        return self.prices[k + self.levels]


@dataclass(frozen=True)
class LevelOrder:
    level: int
    side: Side
    price: Decimal
    qty: Decimal


@dataclass(frozen=True)
class CatchUp:
    """MS8: what the Massager owes at start. ``qty`` 0 means nothing."""

    level: int
    side: Side | None
    qty: Decimal


def _sign(x: Decimal) -> int:
    return (x > 0) - (x < 0)


def _on_step(qty: Decimal, step: Decimal) -> bool:
    return step <= 0 or (qty / step) == (qty / step).to_integral_value()


def lattice(params: MassagerParams, tick: Decimal) -> Lattice:
    """MS5. Assumes the params passed check_start (or MS3 at least)."""
    levels = int(params.swing / params.clip)
    center = (params.band_low + params.band_high) / 2
    step = (params.band_high - params.band_low) / (2 * levels)
    prices = tuple(
        ((center + k * step) / tick).to_integral_value(rounding=ROUND_HALF_UP) * tick
        for k in range(-levels, levels + 1)
    )
    return Lattice(levels=levels, center=center, step=step, prices=prices)


def check_start(
    params: MassagerParams, *, position: Decimal, mid: Decimal, venue: Venue
) -> Lattice:
    """MS1–MS6. Returns the lattice it would run, or raises MassagerRefused."""
    if position == 0:
        raise MassagerRefused("MS1", "A Massager needs an open Position")
    low, high = params.band_low, params.band_high
    if low <= 0 or high <= 0 or low >= high:
        raise MassagerRefused("MS2", "The Band needs a low below its high, both above 0")
    if not low <= mid <= high:
        raise MassagerRefused("MS2", "Price is outside the Band")
    if params.swing <= 0 or params.clip <= 0:
        raise MassagerRefused("MS3", "Set the Swing and the Clip")
    whole = params.swing / params.clip
    if whole != whole.to_integral_value():
        raise MassagerRefused("MS3", "The Swing must be a whole number of Clips")
    if params.clip < venue.min_qty:
        raise MassagerRefused("MS3", "The Clip is under the venue minimum")
    if not _on_step(params.clip, venue.size_step):
        raise MassagerRefused("MS3", "The Clip is not on the Market's size step")
    if params.swing >= abs(position):
        raise MassagerRefused("MS4", "The Swing must be smaller than the Core")
    grid = lattice(params, venue.tick)
    need = grid.center * 2 * venue.maker_bps / BPS + venue.tick
    if grid.step < need:
        raise MassagerRefused(
            "MS6", "A Step does not clear the fees: widen the Band or use fewer Clips"
        )
    return grid


def catch_up(grid: Lattice, params: MassagerParams, mid: Decimal) -> CatchUp:
    """MS8: the levels the mid has passed, at or behind it, on its side of the Center."""
    offset = (mid - grid.center) / grid.step
    if offset >= 0:
        k = int(offset.to_integral_value(rounding=ROUND_FLOOR))
    else:
        k = int(offset.to_integral_value(rounding=ROUND_CEILING))
    k = max(-grid.levels, min(grid.levels, k))
    if k == 0:
        return CatchUp(level=0, side=None, qty=ZERO)
    return CatchUp(level=k, side="sell" if k > 0 else "buy", qty=abs(k) * params.clip)


def resting(grid: Lattice, params: MassagerParams, level: int) -> tuple[LevelOrder, ...]:
    """MS9: sells on the next levels up, buys on the next levels down, none past the edge."""
    out: list[LevelOrder] = []
    for j in range(1, RESTING_EACH_SIDE + 1):
        up = level + j
        if up <= grid.levels:
            out.append(LevelOrder(up, "sell", grid.price(up), params.clip))
    for j in range(1, RESTING_EACH_SIDE + 1):
        down = level - j
        if down >= -grid.levels:
            out.append(LevelOrder(down, "buy", grid.price(down), params.clip))
    return tuple(out)


@dataclass
class Book:
    """What the Massager has done. ``lean`` is signed; ``lean_price`` its average price."""

    level: int = 0
    lean: Decimal = ZERO
    lean_price: Decimal | None = None
    captured: Decimal = ZERO

    def level_filled(self, level: int) -> None:
        """MS9: only a level whose Clip filled in full moves the lattice."""
        self.level = level

    def fill(self, side: Side, qty: Decimal, price: Decimal, fee: Decimal = ZERO) -> None:
        """MS10: average-cost Lean. A reduction realizes; a fill through zero opens the rest."""
        if qty <= 0:
            return
        delta = qty if side == "buy" else -qty
        self.captured -= fee
        prev = self.lean
        if prev == 0 or _sign(prev) == _sign(delta):
            total = abs(prev) + qty
            avg = self.lean_price if self.lean_price is not None else price
            self.lean_price = (avg * abs(prev) + price * qty) / total
            self.lean = prev + delta
            return
        closed = min(abs(prev), qty)
        avg = self.lean_price if self.lean_price is not None else price
        self.captured += (price - avg) * closed * _sign(prev)
        self.lean = prev + delta
        if self.lean == 0:
            self.lean_price = None
        elif _sign(self.lean) != _sign(prev):
            self.lean_price = price


def core(position: Decimal, lean: Decimal) -> Decimal:
    """MS12."""
    return position - lean


def judge(position: Decimal, lean: Decimal, *, core_side: int, swing: Decimal) -> Verdict:
    """MS12: what an outside fill means for the Massager."""
    if position == 0 or _sign(position) != core_side:
        return "stop"
    c = core(position, lean)
    if _sign(c) != core_side or abs(c) <= swing:
        return "pause"
    return "run"


def core_entry_after(entry: Decimal, core_size: Decimal, delta: Decimal, price: Decimal) -> Decimal:
    """MS11: an outside add moves the Core's entry by average cost; a reduction leaves it."""
    if delta == 0 or core_size == 0 or _sign(delta) != _sign(core_size):
        return entry
    return (entry * abs(core_size) + price * abs(delta)) / (abs(core_size) + abs(delta))


def basis(core_entry: Decimal, core_size: Decimal, captured: Decimal) -> Decimal | None:
    """MS11: the Core's entry less Captured per unit, on the side that helps the Core."""
    if core_size == 0:
        return None
    return core_entry - _sign(core_size) * captured / abs(core_size)
