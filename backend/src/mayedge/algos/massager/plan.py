"""Massager planner. Pure: no venue, no clock. Rule ids are docs/massager-rules.md.

Sizes are signed: long above zero, short below. The Position is Core + Lean.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Any, Literal

from mayedge.numbers import fmt_decimal
from mayedge.rows import obj

ALGO_ID = "massager"
ALGO_VERSION = "1"

Side = Literal["buy", "sell"]
Verdict = Literal["run", "pause", "stop"]

BPS = Decimal("10000")
ZERO = Decimal("0")
# MS9: levels resting on each side of the current one.
RESTING_EACH_SIDE = 2
# MS21: ATR length, and how far the live Step must move before the levels follow it.
ATR_LENGTH = 14
REDRAW_SHARE = Decimal("0.20")
ATR_TIMEFRAMES = ("15m", "1h", "4h")
StepMode = Literal["fixed", "atr"]


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
    """What was asked: the Band, the Swing and the Step. ``clip`` is 0 until check_start
    derives it (MS3); after that ``swing`` is the run's Swing, levels × Clip."""

    band_low: Decimal
    band_high: Decimal
    swing: Decimal
    step: Decimal
    clip: Decimal = ZERO
    # MS3, MS21: a Fixed Step never moves; an ATR Step is atr_mult × ATR(14) on atr_tf.
    step_mode: StepMode = "fixed"
    atr_mult: Decimal = ZERO
    atr_tf: str = "1h"

    @property
    def center(self) -> Decimal:
        return (self.band_low + self.band_high) / 2

    @property
    def levels(self) -> int:
        return int(self.swing / self.clip) if self.clip > 0 else 0

    def to_json(self) -> dict[str, Any]:
        return {
            "band_low": fmt_decimal(self.band_low) or "0",
            "band_high": fmt_decimal(self.band_high) or "0",
            "swing": fmt_decimal(self.swing) or "0",
            "step": fmt_decimal(self.step) or "0",
            "clip": fmt_decimal(self.clip) or "0",
            "step_mode": self.step_mode,
            "atr_mult": fmt_decimal(self.atr_mult) or "0",
            "atr_tf": self.atr_tf,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> MassagerParams:
        low = Decimal(str(raw.get("band_low") or "0"))
        high = Decimal(str(raw.get("band_high") or "0"))
        swing = Decimal(str(raw.get("swing") or "0"))
        clip = Decimal(str(raw.get("clip") or "0"))
        step = Decimal(str(raw.get("step") or "0"))
        if step <= 0 and clip > 0 and swing >= clip:
            # A run kept before the Step was typed: its Step was the Band cut evenly.
            step = (high - low) / (2 * int(swing / clip))
        mode: StepMode = "atr" if raw.get("step_mode") == "atr" else "fixed"
        return cls(
            band_low=low,
            band_high=high,
            swing=swing,
            step=step,
            clip=clip,
            step_mode=mode,
            atr_mult=Decimal(str(raw.get("atr_mult") or "0")),
            atr_tf=str(raw.get("atr_tf") or "1h"),
        )


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
    # The level's price before tick rounding: the anchor once the level fills (MS9).
    mark: Decimal = ZERO


@dataclass(frozen=True)
class CatchUp:
    """MS8: what the Massager owes at start. ``qty`` 0 means nothing."""

    level: int
    side: Side | None
    qty: Decimal


def _sign(x: Decimal) -> int:
    return (x > 0) - (x < 0)


def _to_tick(price: Decimal, tick: Decimal) -> Decimal:
    return (price / tick).to_integral_value(rounding=ROUND_HALF_UP) * tick


def fee_floor(center: Decimal, maker_bps: Decimal, tick: Decimal) -> Decimal:
    """MS6: the least Step that clears a round trip's maker fees, plus a tick."""
    return center * 2 * maker_bps / BPS + tick


def live_step(atr: Decimal, params: MassagerParams, *, floor: Decimal) -> Decimal:
    """MS21: k × ATR, kept between the fee floor and half the Band."""
    half = (params.band_high - params.band_low) / 2
    return max(floor, min(half, params.atr_mult * atr))


def should_redraw(resting_at: Decimal, live: Decimal) -> bool:
    """MS21: the levels follow the live Step only once it is 20% or more off."""
    if resting_at <= 0:
        return live > 0
    return abs(live - resting_at) >= resting_at * REDRAW_SHARE


def lattice(params: MassagerParams, tick: Decimal) -> Lattice:
    """MS5. Assumes the params passed check_start, so the Clip is set."""
    levels = params.levels
    center = params.center
    step = params.step
    prices = tuple(_to_tick(center + k * step, tick) for k in range(-levels, levels + 1))
    return Lattice(levels=levels, center=center, step=step, prices=prices)


def check_start(
    params: MassagerParams, *, position: Decimal, mid: Decimal, venue: Venue
) -> tuple[MassagerParams, Lattice]:
    """MS1–MS6. Returns the run's params (Clip derived, Swing whole Clips) and its lattice,
    or raises MassagerRefused."""
    if position == 0:
        raise MassagerRefused("MS1", "A Massager needs an open Position")
    low, high = params.band_low, params.band_high
    if low <= 0 or high <= 0 or low >= high:
        raise MassagerRefused("MS2", "The Band needs a low below its high, both above 0")
    if not low <= mid <= high:
        raise MassagerRefused("MS2", "Price is outside the Band")
    if params.swing <= 0 or params.step <= 0:
        raise MassagerRefused("MS3", "Set the Swing and the Step")
    levels = int(((high - low) / 2 / params.step).to_integral_value(rounding=ROUND_FLOOR))
    if levels < 1:
        raise MassagerRefused("MS3", "The Step is wider than half the Band")
    clip = params.swing / levels
    if venue.size_step > 0:
        clip = (clip / venue.size_step).to_integral_value(rounding=ROUND_FLOOR) * venue.size_step
    if clip <= 0 or clip < venue.min_qty:
        raise MassagerRefused(
            "MS3", "The Clip comes out under the venue minimum: widen the Step or raise the Swing"
        )
    run = replace(params, swing=clip * levels, clip=clip)
    if run.swing >= abs(position):
        raise MassagerRefused("MS4", "The Swing must be smaller than the Core")
    grid = lattice(run, venue.tick)
    if grid.step < fee_floor(grid.center, venue.maker_bps, venue.tick):
        raise MassagerRefused("MS6", "A Step does not clear the fees: widen the Step")
    return run, grid


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


def start_anchor(params: MassagerParams, level: int) -> Decimal:
    """MS9: the anchor a run starts from, the catch-up level's price before rounding."""
    return params.center + level * params.step


def resting(
    params: MassagerParams, *, level: int, anchor: Decimal, step: Decimal, tick: Decimal
) -> tuple[LevelOrder, ...]:
    """MS9: sells a Step and two above the anchor, buys a Step and two below, none past
    ±levels or outside the Band."""
    out: list[LevelOrder] = []
    sides: tuple[tuple[Side, int], ...] = (("sell", 1), ("buy", -1))
    for side, sign in sides:
        for j in range(1, RESTING_EACH_SIDE + 1):
            k = level + sign * j
            if abs(k) > params.levels:
                continue
            mark = anchor + sign * j * step
            price = _to_tick(mark, tick)
            if not params.band_low <= price <= params.band_high:
                continue
            out.append(LevelOrder(k, side, price, params.clip, mark))
    return tuple(out)


@dataclass
class Book:
    """What the Massager has done. ``lean`` is signed; ``lean_price`` its average price."""

    level: int = 0
    lean: Decimal = ZERO
    lean_price: Decimal | None = None
    captured: Decimal = ZERO
    # MS9: what has filled at each level since the lattice last moved.
    level_fills: dict[int, Decimal] = field(default_factory=dict)

    def level_fill(self, level: int, qty: Decimal, clip: Decimal) -> bool:
        """MS9: fills at a level add up; a whole Clip there moves the lattice to it."""
        total = self.level_fills.get(level, ZERO) + qty
        if total < clip:
            self.level_fills[level] = total
            return False
        self.level = level
        self.level_fills.clear()
        return True

    def qty_for(self, order: LevelOrder, swing: Decimal) -> Decimal:
        """MS9: what is left of the level's Clip, never taking the Lean past the Swing."""
        left = order.qty - self.level_fills.get(order.level, ZERO)
        room = swing - self.lean if order.side == "buy" else swing + self.lean
        return max(ZERO, min(left, room))

    def to_json(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "lean": str(self.lean),
            "lean_price": str(self.lean_price) if self.lean_price is not None else None,
            "captured": str(self.captured),
            "level_fills": {str(k): str(v) for k, v in self.level_fills.items()},
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Book:
        price = raw.get("lean_price")
        fills = obj(raw.get("level_fills"))
        return cls(
            level=int(raw.get("level") or 0),
            lean=Decimal(str(raw.get("lean") or "0")),
            lean_price=Decimal(str(price)) if price is not None else None,
            captured=Decimal(str(raw.get("captured") or "0")),
            level_fills={int(k): Decimal(str(v)) for k, v in fills.items()},
        )

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
