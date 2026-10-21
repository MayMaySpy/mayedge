"""What a Planner is asked to do: its entry, stop, targets and Trails, as the ticket sends them.

The rules are docs/planner-rules.md; rule ids are in comments.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from mayedge.algos.planner.config import (
    DEFAULT_SLIPPAGE,
    MAX_SLIPPAGE,
)
from mayedge.algos.trail import engine
from mayedge.numbers import fmt_decimal, parse_decimal

Side = Literal["buy", "sell"]
Mode = Literal["enter", "attach"]
EntryType = Literal["market", "limit", "trail", "chase", "ladder"]
TargetKind = Literal["price", "r"]
StopSteps = Literal["off", "breakeven", "ladder"]
# P9: a resting reduce-only limit, a Take Profit Limit that waits off the book, or a Trail.
TargetOrder = Literal["limit", "trigger", "trail"]
Reference = Literal["mark", "last"]
# A Trail target or Trail stop distance: R multiples or % of the best price.
TrailUnit = Literal["r", "pct"]
TrailStopStart = Literal["target", "last", "r"]
# Two ticks at least (trail-rules S3).
MIN_TRAIL_TICKS = 2

HUNDRED = Decimal("100")
BPS = Decimal("10000")
ZERO = Decimal("0")


class PlanRefused(ValueError):
    """A plan that breaks a rule. ``rule`` is its id in planner-rules.md."""

    def __init__(self, rule: str, message: str) -> None:
        super().__init__(message)
        self.rule = rule
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"rule": self.rule, "message": self.message}


def _trail_distance(raw: Any, rule: str) -> Decimal:
    try:
        d = parse_decimal(str(raw or ""))
    except ValueError:
        raise PlanRefused(rule, "Set the trail distance") from None
    if d <= 0:
        raise PlanRefused(rule, "The trail distance must be above 0")
    return d


@dataclass(frozen=True)
class Target:
    kind: TargetKind
    value: Decimal
    pct: Decimal
    order: TargetOrder = "limit"
    # P9 Trail: how far behind the best price it follows once its price is reached.
    trail_distance: Decimal | None = None
    trail_unit: TrailUnit = "r"

    def to_json(self) -> dict[str, str]:
        out = {
            "kind": self.kind,
            "value": fmt_decimal(self.value) or "0",
            "pct": fmt_decimal(self.pct) or "0",
            "order": self.order,
        }
        if self.order == "trail":
            out["trail_distance"] = fmt_decimal(self.trail_distance) or "0"
            out["trail_unit"] = self.trail_unit
        return out

    @classmethod
    def from_json(cls, raw: Any) -> Target:
        if not isinstance(raw, dict):
            raise PlanRefused("P5", "Each target needs a price or R and a %")
        kind = raw.get("kind")
        if kind not in ("price", "r"):
            raise PlanRefused("P5", "A target is a price or an R multiple")
        try:
            value = parse_decimal(str(raw.get("value") or ""))
            pct = parse_decimal(str(raw.get("pct") or ""))
        except ValueError:
            raise PlanRefused("P5", "Each target needs a price or R and a %") from None
        # P9: saved before the choice, every target was a Trigger.
        order = raw.get("order") or "trigger"
        if order not in ("limit", "trigger", "trail"):
            raise PlanRefused("P9", "A target is a Limit, a Trigger or a Trail")
        if order != "trail":
            return cls(kind=kind, value=value, pct=pct, order=order)
        unit = raw.get("trail_unit") or "r"
        if unit not in ("r", "pct"):
            raise PlanRefused("P9", "A Trail target's distance is in R or %")
        return cls(
            kind=kind,
            value=value,
            pct=pct,
            order="trail",
            trail_distance=_trail_distance(raw.get("trail_distance"), "P9"),
            trail_unit=unit,
        )


@dataclass(frozen=True)
class EntryTrail:
    """E9: a Trail entry follows the best price from its Activation."""

    distance: Decimal
    distance_kind: engine.DistanceKind = "pct"
    activation: Decimal | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "distance": fmt_decimal(self.distance) or "0",
            "distance_kind": self.distance_kind,
            "activation": fmt_decimal(self.activation),
        }

    @classmethod
    def from_json(cls, raw: Any) -> EntryTrail:
        if not isinstance(raw, dict):
            raise PlanRefused("E9", "Set the Trail entry's distance")
        kind = raw.get("distance_kind") or "pct"
        if kind not in ("pct", "price"):
            raise ValueError("entry_trail.distance_kind must be pct or price")
        return cls(
            distance=_trail_distance(raw.get("distance"), "E9"),
            distance_kind=kind,
            activation=_opt_decimal(raw.get("activation")),
        )


@dataclass(frozen=True)
class EntryChase:
    """E10: a Chase entry works the size behind the touch, inside its band."""

    low: Decimal
    high: Decimal
    offset_bps: Decimal = Decimal("4")
    # The most one Clip shows. None works the whole size at once.
    clip: Decimal | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "low": fmt_decimal(self.low) or "0",
            "high": fmt_decimal(self.high) or "0",
            "offset_bps": fmt_decimal(self.offset_bps) or "0",
            "clip": fmt_decimal(self.clip),
        }

    @classmethod
    def from_json(cls, raw: Any) -> EntryChase:
        if not isinstance(raw, dict):
            raise PlanRefused("E11", "Set the Chase entry's band")
        try:
            low = parse_decimal(str(raw.get("low") or ""))
            high = parse_decimal(str(raw.get("high") or ""))
        except ValueError:
            raise PlanRefused("E11", "Set the Chase entry's band") from None
        if low <= 0 or high <= low:
            raise PlanRefused("E11", "The band's low must be above 0 and under its high")
        offset = _opt_decimal(raw.get("offset_bps"))
        if offset is not None and offset < 0:
            raise PlanRefused("E10", "The offset can't be negative")
        clip = _opt_decimal(raw.get("clip"))
        if clip is not None and clip <= 0:
            clip = None
        return cls(
            low=low,
            high=high,
            offset_bps=offset if offset is not None else Decimal("4"),
            clip=clip,
        )


@dataclass(frozen=True)
class EntryLadder:
    """EL1: a Ladder entry rests its rungs evenly from one price to another."""

    price_from: Decimal
    price_to: Decimal
    rungs: int
    # The Ladder algo's size skew: -1 more size at the low price, 0 even, +1 at the high.
    strength: Decimal = Decimal("0")

    def to_json(self) -> dict[str, Any]:
        return {
            "price_from": fmt_decimal(self.price_from) or "0",
            "price_to": fmt_decimal(self.price_to) or "0",
            "rungs": self.rungs,
            "strength": fmt_decimal(self.strength) or "0",
        }

    @classmethod
    def from_json(cls, raw: Any) -> EntryLadder:
        if not isinstance(raw, dict):
            raise PlanRefused("EL1", "Set the Ladder entry's prices and rungs")
        try:
            price_from = parse_decimal(str(raw.get("price_from") or ""))
            price_to = parse_decimal(str(raw.get("price_to") or ""))
        except ValueError:
            raise PlanRefused("EL1", "Set the Ladder entry's from and to prices") from None
        if price_from <= 0 or price_to <= 0 or price_from == price_to:
            raise PlanRefused("EL1", "The Ladder's from and to are two prices above 0")
        try:
            rungs = int(str(raw.get("rungs") or ""))
        except ValueError:
            raise PlanRefused("EL4", "Set the number of rungs") from None
        strength = _opt_decimal(raw.get("strength")) or Decimal("0")
        if strength < -1 or strength > 1:
            raise PlanRefused("EL1", "Strength is even, low or high")
        return cls(price_from=price_from, price_to=price_to, rungs=rungs, strength=strength)

    def ends(self, side: Side) -> tuple[Decimal, Decimal]:
        """The first rung and the last: a buy runs down from the higher price, a sell up."""
        lo, hi = sorted((self.price_from, self.price_to))
        return (hi, lo) if side == "buy" else (lo, hi)


@dataclass(frozen=True)
class TrailStop:
    """M10: when the stop starts to trail, and how far behind the best price."""

    start: TrailStopStart
    distance: Decimal
    unit: TrailUnit = "r"
    # The target number for start "target".
    after: int = 1
    # The R multiple for start "r".
    at_r: Decimal | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "distance": fmt_decimal(self.distance) or "0",
            "unit": self.unit,
            "after": self.after,
            "at_r": fmt_decimal(self.at_r),
        }

    @classmethod
    def from_json(cls, raw: Any) -> TrailStop | None:
        if not isinstance(raw, dict) or raw.get("start") in (None, "", "off"):
            return None
        start = raw.get("start")
        if start not in ("target", "last", "r"):
            raise ValueError("trail_stop.start must be off, target, last or r")
        unit = raw.get("unit") or "r"
        if unit not in ("r", "pct"):
            raise ValueError("trail_stop.unit must be r or pct")
        at_r = _opt_decimal(raw.get("at_r"))
        if start == "r" and (at_r is None or at_r <= 0):
            raise PlanRefused("M10", "Set the R multiple the stop starts trailing at")
        try:
            after = int(raw.get("after") or 1)
        except (TypeError, ValueError):
            after = 1
        return cls(
            start=start,
            distance=_trail_distance(raw.get("distance"), "M10"),
            unit=unit,
            after=max(1, after),
            at_r=at_r,
        )


@dataclass
class PlannerParams:
    mode: Mode
    side: Side
    stop: Decimal
    targets: list[Target]
    entry_type: EntryType = "limit"
    entry_price: Decimal | None = None
    size: Decimal | None = None
    risk_pct: Decimal | None = None
    stop_steps: StopSteps = "breakeven"
    expiry_min: int | None = None
    slippage: float = DEFAULT_SLIPPAGE
    entry_trail: EntryTrail | None = None
    trail_stop: TrailStop | None = None
    reference: Reference = "mark"
    entry_chase: EntryChase | None = None
    entry_ladder: EntryLadder | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "entry_trail": self.entry_trail.to_json() if self.entry_trail else None,
            "entry_chase": self.entry_chase.to_json() if self.entry_chase else None,
            "entry_ladder": self.entry_ladder.to_json() if self.entry_ladder else None,
            "trail_stop": self.trail_stop.to_json() if self.trail_stop else None,
            "reference": self.reference,
            "mode": self.mode,
            "side": self.side,
            "stop": fmt_decimal(self.stop) or "0",
            "targets": [t.to_json() for t in self.targets],
            "entry_type": self.entry_type,
            "entry_price": fmt_decimal(self.entry_price),
            "size": fmt_decimal(self.size),
            "risk_pct": fmt_decimal(self.risk_pct),
            "stop_steps": self.stop_steps,
            "expiry_min": self.expiry_min,
            "slippage": self.slippage,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> PlannerParams:
        """Parse a start body or a stored row. Shape errors refuse; rules are build_plan's."""
        mode = raw.get("mode") or "enter"
        if mode not in ("enter", "attach"):
            raise ValueError("mode must be enter or attach")
        side = raw.get("side")
        if side not in ("buy", "sell"):
            raise ValueError("side must be buy or sell")
        entry_type = raw.get("entry_type") or "limit"
        if entry_type not in ("market", "limit", "trail", "chase", "ladder"):
            raise ValueError("entry_type must be market, limit, trail, chase or ladder")
        reference = raw.get("reference") or "mark"
        if reference not in ("mark", "last"):
            raise ValueError("reference must be mark or last")
        try:
            stop = parse_decimal(str(raw.get("stop") or ""))
        except ValueError:
            raise PlanRefused("S1", "Set a stop") from None
        targets_raw = raw.get("targets") or []
        if not isinstance(targets_raw, list):
            raise PlanRefused("P5", "Targets must be a list")
        expiry = raw.get("expiry_min")
        return cls(
            mode=mode,
            side=side,
            stop=stop,
            targets=[Target.from_json(t) for t in targets_raw],
            entry_type=entry_type,
            entry_price=_opt_decimal(raw.get("entry_price")),
            size=_opt_decimal(raw.get("size")),
            risk_pct=_opt_decimal(raw.get("risk_pct")),
            stop_steps=_stop_steps(raw),
            expiry_min=int(expiry) if expiry not in (None, "", 0, "0") else None,
            slippage=_clamp_slippage(raw.get("slippage")),
            entry_trail=EntryTrail.from_json(raw.get("entry_trail"))
            if entry_type == "trail"
            else None,
            entry_chase=EntryChase.from_json(raw.get("entry_chase"))
            if entry_type == "chase"
            else None,
            entry_ladder=(
                EntryLadder.from_json(raw.get("entry_ladder")) if entry_type == "ladder" else None
            ),
            trail_stop=TrailStop.from_json(raw.get("trail_stop")),
            reference=reference,
        )

    def trails(self) -> bool:
        """Any part of this plan follows the price (F9: Last needs the Market's prints)."""
        return (
            self.entry_type == "trail"
            or self.trail_stop is not None
            or any(t.order == "trail" for t in self.targets)
        )


@dataclass(frozen=True)
class MarketContext:
    """What the venue says right now. Signed position size: + long, − short."""

    tick: Decimal
    qty_step: Decimal
    min_qty: Decimal
    mark: Decimal
    equity: Decimal | None = None
    taker_bps: Decimal = Decimal("0")
    liq_price: Decimal | None = None
    position_size: Decimal = Decimal("0")
    position_entry: Decimal | None = None
    # EL4: limit orders already resting on this Market.
    resting_orders: int = 0
    # EL1: a rung must meet the venue minimum at its own price, not at mark.
    min_base: Decimal = Decimal("0")
    min_quote: Decimal = Decimal("0")


def _opt_decimal(raw: object) -> Decimal | None:
    if raw is None or raw == "":
        return None
    return parse_decimal(str(raw))


def _stop_steps(raw: dict[str, Any]) -> StopSteps:
    steps = raw.get("stop_steps")
    if steps in ("off", "breakeven", "ladder"):
        return steps
    if steps is not None:
        raise ValueError("stop_steps must be off, breakeven or ladder")
    # Rows from before Stop steps carried a breakeven flag.
    return "breakeven" if raw.get("breakeven", True) else "off"


def _clamp_slippage(raw: object) -> float:
    try:
        slip = float(str(raw)) if raw not in (None, "") else DEFAULT_SLIPPAGE
    except ValueError:
        slip = DEFAULT_SLIPPAGE
    if slip <= 0:
        return DEFAULT_SLIPPAGE
    return min(slip, MAX_SLIPPAGE)
