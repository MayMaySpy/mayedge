"""Planner plan math. Pure: no venue, no clock. Rule ids are docs/planner-rules.md."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from typing import Any, Literal

from mayedge.algos.ladder.config import MAX_WINDOW, MIN_RUNGS
from mayedge.algos.ladder.plan import Rung, build_rungs
from mayedge.algos.planner.config import (
    DEFAULT_SLIPPAGE,
    MARKET_ORDER_CAP,
    MAX_SLIPPAGE,
    MAX_TARGETS,
)
from mayedge.algos.trail import engine
from mayedge.numbers import fmt_decimal, parse_decimal

ALGO_ID = "planner"
ALGO_VERSION = "1"

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
            entry_trail=EntryTrail.from_json(raw.get("entry_trail")) if entry_type == "trail" else None,
            entry_chase=EntryChase.from_json(raw.get("entry_chase")) if entry_type == "chase" else None,
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


@dataclass(frozen=True)
class PlannedTarget:
    index: int
    price: Decimal
    qty: Decimal
    pct: Decimal
    r: Decimal
    move_pct: Decimal
    order: TargetOrder = "trigger"
    # A Trail target's distance, in price ("price") or % of the best price ("pct").
    trail_distance: Decimal | None = None
    trail_kind: engine.DistanceKind = "price"
    # P10: what closing qty at price makes, less the taker fee there.
    usd: Decimal = Decimal("0")

    def to_json(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "price": fmt_decimal(self.price) or "0",
            "qty": fmt_decimal(self.qty) or "0",
            "pct": fmt_decimal(self.pct) or "0",
            "r": fmt_decimal(self.r) or "0",
            "move_pct": fmt_decimal(self.move_pct) or "0",
            "order": self.order,
            "trail_distance": fmt_decimal(self.trail_distance),
            "trail_kind": self.trail_kind,
            "usd": fmt_decimal(self.usd) or "0",
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> PlannedTarget:
        return cls(
            index=int(raw["index"]),
            price=Decimal(str(raw["price"])),
            qty=Decimal(str(raw["qty"])),
            pct=Decimal(str(raw["pct"])),
            r=Decimal(str(raw.get("r") or "0")),
            move_pct=Decimal(str(raw.get("move_pct") or "0")),
            order=raw["order"] if raw.get("order") in ("limit", "trail") else "trigger",
            trail_distance=_opt_decimal(raw.get("trail_distance")),
            trail_kind="pct" if raw.get("trail_kind") == "pct" else "price",
            usd=Decimal(str(raw.get("usd") or "0")),
        )


@dataclass(frozen=True)
class PlannedStep:
    """M2: once target ``after`` fills in full, the stop moves to ``price``."""

    after: int
    price: Decimal
    to: str  # "breakeven" or "tp1", "tp2"…

    def to_json(self) -> dict[str, Any]:
        return {"after": self.after, "price": fmt_decimal(self.price) or "0", "to": self.to}

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> PlannedStep:
        return cls(after=int(raw["after"]), price=Decimal(str(raw["price"])), to=str(raw["to"]))


@dataclass(frozen=True)
class Plan:
    side: Side
    entry: Decimal
    stop: Decimal
    r: Decimal
    size: Decimal
    targets: tuple[PlannedTarget, ...]
    runner: Decimal
    risk_usd: Decimal
    risk_pct: Decimal | None
    breakeven: Decimal
    stop_pct: Decimal
    warnings: tuple[str, ...] = field(default_factory=tuple)
    steps: tuple[PlannedStep, ...] = field(default_factory=tuple)
    # EL1: a Ladder entry's rungs, nearest the market first. Empty once the entry ends.
    rungs: tuple[Rung, ...] = field(default_factory=tuple)

    def to_json(self) -> dict[str, Any]:
        return {
            "side": self.side,
            "entry": fmt_decimal(self.entry) or "0",
            "stop": fmt_decimal(self.stop) or "0",
            "r": fmt_decimal(self.r) or "0",
            "size": fmt_decimal(self.size) or "0",
            "targets": [t.to_json() for t in self.targets],
            "runner": fmt_decimal(self.runner) or "0",
            "risk_usd": fmt_decimal(self.risk_usd) or "0",
            "risk_pct": fmt_decimal(self.risk_pct),
            "breakeven": fmt_decimal(self.breakeven) or "0",
            "stop_pct": fmt_decimal(self.stop_pct) or "0",
            "warnings": list(self.warnings),
            "steps": [step.to_json() for step in self.steps],
            "rungs": [
                {"index": r.index, "price": fmt_decimal(r.price) or "0", "qty": fmt_decimal(r.qty) or "0"}
                for r in self.rungs
            ],
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Plan:
        risk_pct = raw.get("risk_pct")
        return cls(
            side=raw["side"],
            entry=Decimal(str(raw["entry"])),
            stop=Decimal(str(raw["stop"])),
            r=Decimal(str(raw["r"])),
            size=Decimal(str(raw["size"])),
            targets=tuple(PlannedTarget.from_json(t) for t in raw.get("targets") or []),
            runner=Decimal(str(raw.get("runner") or "0")),
            risk_usd=Decimal(str(raw.get("risk_usd") or "0")),
            risk_pct=Decimal(str(risk_pct)) if risk_pct not in (None, "") else None,
            breakeven=Decimal(str(raw.get("breakeven") or "0")),
            stop_pct=Decimal(str(raw.get("stop_pct") or "0")),
            warnings=tuple(str(w) for w in raw.get("warnings") or []),
            steps=tuple(PlannedStep.from_json(x) for x in raw.get("steps") or []),
            rungs=tuple(
                Rung(index=int(x["index"]), price=Decimal(str(x["price"])), qty=Decimal(str(x["qty"])))
                for x in raw.get("rungs") or []
            ),
        )


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


def _sign(side: Side) -> int:
    return 1 if side == "buy" else -1


def round_price(price: Decimal, tick: Decimal, *, up: bool) -> Decimal:
    if tick <= 0:
        return price
    n = (price / tick).to_integral_value(rounding=ROUND_UP if up else ROUND_DOWN)
    return n * tick


def round_qty(qty: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return qty
    return (qty / step).to_integral_value(rounding=ROUND_DOWN) * step


def _move_pct(side: Side, entry: Decimal, price: Decimal) -> Decimal:
    """P8: signed % from entry, + on the winning side."""
    if entry <= 0:
        return Decimal("0")
    return (price - entry) / entry * HUNDRED * _sign(side)


def breakeven_price(side: Side, entry: Decimal, *, taker_bps: Decimal, tick: Decimal) -> Decimal:
    """M3: entry plus the round-trip taker fee, rounded away from entry."""
    fee = entry * taker_bps * 2 / BPS
    if side == "buy":
        return round_price(entry + fee, tick, up=True)
    return round_price(entry - fee, tick, up=False)


def stop_price(side: Side, stop: Decimal, tick: Decimal) -> Decimal:
    """P6: the stop rounds away from entry."""
    return round_price(stop, tick, up=side == "sell")


def entry_price(params: PlannerParams, ctx: MarketContext) -> Decimal:
    """P1: the price a plan is drawn from before anything has filled."""
    if params.mode == "attach":
        if ctx.position_entry is None or ctx.position_entry <= 0:
            raise PlanRefused("S4", "The Position has no entry price")
        return ctx.position_entry
    if params.entry_type == "market":
        if ctx.mark <= 0:
            raise PlanRefused("S1", "No mark to price a Market entry")
        return ctx.mark
    if params.entry_type == "trail":
        return trail_entry_now(params, ctx)
    if params.entry_type == "chase":
        return chase_worst_fill(params, ctx.tick)
    if params.entry_type == "ladder":
        return ladder_full_fill(params, ctx.tick)
    if params.entry_price is None or params.entry_price <= 0:
        raise PlanRefused("S1", "Set the Limit entry price")
    # A buy rests at or below what was typed, a sell at or above.
    return round_price(params.entry_price, ctx.tick, up=params.side == "sell")


def chase_worst_fill(params: PlannerParams, tick: Decimal) -> Decimal:
    """E12: the worst price a Chase entry can fill at, its band's high for a buy, low for a sell."""
    ec = params.entry_chase
    if ec is None:
        raise PlanRefused("E11", "Set the Chase entry's band")
    if params.side == "buy":
        return round_price(ec.high, tick, up=False)
    return round_price(ec.low, tick, up=True)


def _entry_ladder(params: PlannerParams) -> EntryLadder:
    el = params.entry_ladder
    if el is None:
        raise PlanRefused("EL1", "Set the Ladder entry's prices and rungs")
    if el.rungs < MIN_RUNGS or el.rungs > MAX_WINDOW:
        raise PlanRefused("EL4", f"A Ladder entry has {MIN_RUNGS} to {MAX_WINDOW} rungs")
    return el


def ladder_rungs(
    params: PlannerParams,
    *,
    size: Decimal,
    tick: Decimal,
    qty_step: Decimal,
    min_qty: Decimal,
    min_quote: Decimal = Decimal("0"),
) -> list[Rung]:
    """EL1: the Ladder algo's rungs for this size. qty_step 0 gives the exact weights."""
    el = _entry_ladder(params)
    first, last = el.ends(params.side)
    try:
        return build_rungs(
            side=params.side,
            qty=size,
            price_from=first,
            price_to=last,
            rungs=el.rungs,
            tick=tick,
            qty_step=qty_step,
            min_qty=min_qty,
            size_skew=el.strength,
            min_quote=min_quote,
        )
    except ValueError as e:
        raise PlanRefused("EL1", str(e)) from None


def ladder_full_fill(params: PlannerParams, tick: Decimal) -> Decimal:
    """EL2: the average with every rung filled."""
    weights = ladder_rungs(params, size=Decimal("1"), tick=tick, qty_step=Decimal("0"), min_qty=Decimal("0"))
    avg = sum((r.price * r.qty for r in weights), Decimal("0"))
    # Rounded the worse way, so R is never drawn smaller than the rungs make it.
    return round_price(avg, tick, up=params.side == "buy")


def ladder_furthest(params: PlannerParams, tick: Decimal) -> Decimal:
    """EL2: the rung nearest the stop."""
    weights = ladder_rungs(params, size=Decimal("1"), tick=tick, qty_step=Decimal("0"), min_qty=Decimal("0"))
    return weights[-1].price


def entry_follow(params: PlannerParams, tick: Decimal) -> engine.Follow:
    """E9: what a Trail entry follows. A buy follows the low, a sell the high."""
    et = params.entry_trail
    if et is None:
        raise PlanRefused("E9", "Set the Trail entry's distance")
    return engine.Follow(
        side=params.side,
        distance=et.distance,
        distance_kind=et.distance_kind,
        tick=tick,
        activation=et.activation,
    )


def trail_entry_now(params: PlannerParams, ctx: MarketContext) -> Decimal:
    """P1 for a Trail entry: where it would fire if the best price were its start now."""
    if ctx.mark <= 0:
        raise PlanRefused("S1", "No mark to price a Trail entry")
    f = entry_follow(params, ctx.tick)
    _check_trail_ticks(f.distance, f.distance_kind, ctx, "E9")
    if f.activation is not None:
        if f.activation <= 0:
            raise PlanRefused("E9", "The Activation must be above 0")
        if engine.reached(f, ctx.mark, f.activation):
            raise PlanRefused("E9", "Mark is already past the Activation")
    return engine.trigger_at(f, f.activation if f.activation is not None else ctx.mark)


def _check_trail_ticks(distance: Decimal, kind: str, ctx: MarketContext, rule: str) -> None:
    at = ctx.mark * distance / HUNDRED if kind == "pct" else distance
    if kind == "pct" and distance >= HUNDRED:
        raise PlanRefused(rule, "The trail distance must be under 100%")
    if ctx.tick > 0 and ctx.mark > 0 and at < ctx.tick * MIN_TRAIL_TICKS:
        raise PlanRefused(rule, f"The trail distance is under {MIN_TRAIL_TICKS} ticks")


def trail_price_distance(unit: TrailUnit, distance: Decimal, r: Decimal) -> tuple[Decimal, engine.DistanceKind]:
    """An R distance becomes a price; a % stays a % of the best price."""
    if unit == "r":
        return distance * r, "price"
    return distance, "pct"


def _check_targets_shape(targets: list[Target], *, trail_stop: bool = False) -> None:
    if not targets:
        if trail_stop:
            return  # P5: all Runner, on a trailing stop
        raise PlanRefused("P5", "Add at least one target")
    if len(targets) > MAX_TARGETS:
        raise PlanRefused("P5", f"At most {MAX_TARGETS} targets")
    total = Decimal("0")
    for t in targets:
        if t.pct <= 0:
            raise PlanRefused("P5", "Each target closes more than 0%")
        if t.value <= 0:
            raise PlanRefused("P5", "Each target needs a price or R above 0")
        total += t.pct
    if total > HUNDRED:
        raise PlanRefused("P5", "Targets add up to more than 100%")


@dataclass(frozen=True)
class _Leg:
    price: Decimal
    pct: Decimal
    order: TargetOrder
    qty: Decimal = Decimal("0")
    trail_distance: Decimal | None = None
    trail_unit: TrailUnit = "r"
    # The target this leg sizes, when resizing a plan already on (M6).
    index: int = 0


def _target_prices(
    side: Side, entry: Decimal, r: Decimal, targets: list[Target], tick: Decimal
) -> list[_Leg]:
    """Each target's price, P4 and P6, nearest entry first."""
    out: list[_Leg] = []
    sign = _sign(side)
    for t in targets:
        raw = entry + sign * r * t.value if t.kind == "r" else t.value
        # Targets round toward entry.
        out.append(
            _Leg(
                round_price(raw, tick, up=side == "sell"),
                t.pct,
                t.order,
                trail_distance=t.trail_distance,
                trail_unit=t.trail_unit,
            )
        )
    out.sort(key=lambda leg: leg.price * sign)
    return out


def _size_targets(
    priced: list[_Leg],
    *,
    size: Decimal,
    qty_step: Decimal,
    min_qty: Decimal,
) -> tuple[list[_Leg], list[str]]:
    """Each target's size. P5 Runner, P6 rounding, P7 merges."""
    legs = list(priced)
    warnings: list[str] = []
    if not legs:
        return [], warnings
    while legs:
        total_pct = sum((leg.pct for leg in legs), Decimal("0"))
        closing = round_qty(size * total_pct / HUNDRED, qty_step)
        sized: list[_Leg] = []
        used = Decimal("0")
        for i, leg in enumerate(legs):
            if i == len(legs) - 1:
                qty = closing - used
            else:
                qty = round_qty(size * leg.pct / HUNDRED, qty_step)
            used += qty
            sized.append(dataclasses.replace(leg, qty=qty))
        small = next((i for i, leg in enumerate(sized) if leg.qty <= 0 or leg.qty < min_qty), None)
        if small is None:
            return sized, warnings
        if len(legs) == 1:
            break
        gone = legs.pop(small)
        price = gone.price
        into = small if small < len(legs) else small - 1
        keep = legs[into]
        keep_price = keep.price
        # The joined target keeps its own price and order type (P7).
        legs[into] = dataclasses.replace(keep, pct=keep.pct + gone.pct)
        warnings.append(
            f"Target at {fmt_decimal(price)} is below the venue minimum and joins "
            f"the one at {fmt_decimal(keep_price)}"
        )
    raise PlanRefused("P7", "The size is too small for any target at the venue minimum")


def price_plan(
    *,
    side: Side,
    entry: Decimal,
    stop: Decimal,
    size: Decimal,
    targets: list[Target],
    ctx: MarketContext,
    risk_pct: Decimal | None = None,
    stop_steps: StopSteps = "breakeven",
    trail_stop: TrailStop | None = None,
) -> Plan:
    """Draw a plan at a known entry and size. The job calls this again after the fill."""
    _check_targets_shape(targets, trail_stop=trail_stop is not None)
    stop = stop_price(side, stop, ctx.tick)
    sign = _sign(side)
    if (entry - stop) * sign <= 0:
        raise PlanRefused("S1", "The stop is on the winning side of entry")
    r = abs(entry - stop)
    priced = _target_prices(side, entry, r, targets, ctx.tick)
    for leg in priced:
        if (leg.price - entry) * sign <= 0:
            raise PlanRefused("S1", f"Target {fmt_decimal(leg.price)} is not past entry")
    if size <= 0:
        raise PlanRefused("P2", "Size is 0")
    sized, warnings = _size_targets(
        priced, size=size, qty_step=ctx.qty_step, min_qty=ctx.min_qty
    )
    planned = tuple(_planned_target(i + 1, leg, side=side, entry=entry, r=r, ctx=ctx) for i, leg in enumerate(sized))
    closing = sum((t.qty for t in planned), Decimal("0"))
    be = breakeven_price(side, entry, taker_bps=ctx.taker_bps, tick=ctx.tick)
    steps = plan_steps(stop_steps, planned, size=size, breakeven=be)
    fee_at_stop = stop * ctx.taker_bps / BPS
    risk_usd = size * (r + fee_at_stop)
    risk_of_equity = None
    if ctx.equity is not None and ctx.equity > 0:
        risk_of_equity = risk_usd / ctx.equity * HUNDRED
    return Plan(
        side=side,
        entry=entry,
        stop=stop,
        r=r,
        size=size,
        targets=planned,
        runner=size - closing,
        risk_usd=risk_usd,
        risk_pct=risk_of_equity if risk_of_equity is not None else risk_pct,
        breakeven=be,
        stop_pct=_move_pct(side, entry, stop),
        warnings=tuple(warnings),
        steps=steps,
    )


def _planned_target(
    index: int, leg: _Leg, *, side: Side, entry: Decimal, r: Decimal, ctx: MarketContext
) -> PlannedTarget:
    distance: Decimal | None = None
    kind: engine.DistanceKind = "price"
    if leg.order == "trail" and leg.trail_distance is not None:
        distance, kind = trail_price_distance(leg.trail_unit, leg.trail_distance, r)
        _check_trail_ticks(distance, kind, ctx, "P9")
    return PlannedTarget(
        index=index,
        price=leg.price,
        qty=leg.qty,
        pct=leg.pct,
        r=(abs(leg.price - entry) / r) if r > 0 else Decimal("0"),
        move_pct=_move_pct(side, entry, leg.price),
        order=leg.order,
        trail_distance=distance,
        trail_kind=kind,
        usd=target_usd(entry, leg.price, leg.qty, taker_bps=ctx.taker_bps),
    )


def target_usd(entry: Decimal, price: Decimal, qty: Decimal, *, taker_bps: Decimal) -> Decimal:
    """P10: closing qty at a target from entry, less the taker fee at the target."""
    return qty * (abs(price - entry) - price * taker_bps / BPS)


def resize_targets(
    plan: Plan,
    *,
    filled: dict[int, Decimal],
    expected: Decimal,
    held: Decimal,
    stop_steps: StopSteps,
    ctx: MarketContext,
) -> tuple[Plan, list[str]]:
    """M6: what each target has left becomes the same share of the Position now.

    ``filled`` is what each target has closed so far, ``expected`` the Position
    from Planner's own fills, ``held`` the Position now. Filled parts stay as
    they are. P6 rounding and P7 joins apply to what is left.
    """
    if expected <= 0 or held <= 0:
        return plan, []
    left = {t.index: max(ZERO, t.qty - filled.get(t.index, ZERO)) for t in plan.targets}
    open_targets = [t for t in plan.targets if left[t.index] > 0]
    legs = [
        _Leg(price=t.price, pct=left[t.index] / expected * HUNDRED, order=t.order, index=t.index)
        for t in open_targets
    ]
    warnings: list[str] = []
    try:
        sized, warnings = _size_targets(legs, size=held, qty_step=ctx.qty_step, min_qty=ctx.min_qty)
    except PlanRefused:
        sized = []
        warnings = ["The Position is too small for any target at the venue minimum. The stop covers it"]
    new_left = {t.index: ZERO for t in open_targets}
    for leg in sized:
        new_left[leg.index] = leg.qty
    joined_into: dict[int, int] = {}
    for t in open_targets:
        if new_left[t.index] > 0:
            continue
        later = [o.index for o in open_targets if o.index > t.index and new_left[o.index] > 0]
        earlier = [o.index for o in open_targets if o.index < t.index and new_left[o.index] > 0]
        if later:
            joined_into[t.index] = later[0]
        elif earlier:
            joined_into[t.index] = earlier[-1]
    closed = sum(filled.get(t.index, ZERO) for t in plan.targets)
    size = closed + held
    targets = tuple(
        dataclasses.replace(
            t,
            qty=filled.get(t.index, ZERO) + new_left.get(t.index, ZERO),
            usd=target_usd(
                plan.entry,
                t.price,
                filled.get(t.index, ZERO) + new_left.get(t.index, ZERO),
                taker_bps=ctx.taker_bps,
            ),
        )
        for t in plan.targets
    )
    still_open = held
    keep_after: set[int] = set()
    for t in targets:
        still_open -= new_left.get(t.index, ZERO)
        if still_open > 0:
            keep_after.add(t.index)
    steps: list[PlannedStep] = []
    if stop_steps != "off":
        for step in plan.steps:
            after = joined_into.get(step.after, step.after)
            # A step after which nothing would be left open is not drawn (M2).
            if after in keep_after or filled.get(after, ZERO) > 0:
                steps.append(dataclasses.replace(step, after=after))
    scale = size / plan.size if plan.size > 0 else Decimal("1")
    resized = dataclasses.replace(
        plan,
        size=size,
        targets=targets,
        runner=held - sum(new_left.values(), ZERO),
        risk_usd=plan.risk_usd * scale,
        risk_pct=plan.risk_pct * scale if plan.risk_pct is not None else None,
        warnings=tuple(warnings),
        steps=tuple(steps),
    )
    return resized, warnings


def plan_steps(
    mode: StopSteps,
    targets: tuple[PlannedTarget, ...],
    *,
    size: Decimal,
    breakeven: Decimal,
) -> tuple[PlannedStep, ...]:
    """M2: the Stop steps, skipping any after which nothing is left open."""
    if mode == "off" or not targets:
        return ()
    out: list[PlannedStep] = []
    left = size
    for i, t in enumerate(targets):
        left -= t.qty
        if left <= 0:
            break
        if i == 0:
            out.append(PlannedStep(after=1, price=breakeven, to="breakeven"))
        elif mode == "ladder":
            before = targets[i - 1]
            out.append(PlannedStep(after=t.index, price=before.price, to=f"tp{before.index}"))
        if mode == "breakeven":
            break
    return tuple(out)


def plan_size(params: PlannerParams, ctx: MarketContext, *, entry: Decimal, stop: Decimal) -> Decimal:
    if params.mode == "attach":
        return abs(ctx.position_size)
    if params.size is not None and params.risk_pct is not None:
        raise PlanRefused("P2", "Give a size or a risk %, not both")
    if params.size is not None:
        if params.size <= 0:
            raise PlanRefused("P2", "Size must be above 0")
        size = round_qty(params.size, ctx.qty_step)
    elif params.risk_pct is not None:
        if params.risk_pct <= 0:
            raise PlanRefused("P2", "Risk % must be above 0")
        if ctx.equity is None or ctx.equity <= 0:
            raise PlanRefused("P2", "No equity to size the risk from")
        per_unit = abs(entry - stop) + stop * ctx.taker_bps / BPS
        if per_unit <= 0:
            raise PlanRefused("S1", "The stop is at entry")
        size = round_qty(ctx.equity * params.risk_pct / HUNDRED / per_unit, ctx.qty_step)
    else:
        raise PlanRefused("P2", "Give a size or a risk %")
    if size <= 0 or size < ctx.min_qty:
        raise PlanRefused("P2", f"Size is below the venue minimum {fmt_decimal(ctx.min_qty)}")
    return size


def build_plan(params: PlannerParams, ctx: MarketContext) -> Plan:
    """Check the start rules and draw the plan the job will send."""
    sign = _sign(params.side)
    if params.mode == "enter" and ctx.position_size != 0:
        raise PlanRefused("S3", "A Position is already open on this Market. Use Attach")
    if params.mode == "attach":
        if ctx.position_size == 0:
            raise PlanRefused("S4", "No open Position to attach to")
        held: Side = "buy" if ctx.position_size > 0 else "sell"
        if held != params.side:
            raise PlanRefused("S4", "The plan's side is not the Position's side")
    entry = entry_price(params, ctx)
    stop = stop_price(params.side, params.stop, ctx.tick)
    if stop <= 0:
        raise PlanRefused("S1", "Set a stop")
    if (entry - stop) * sign <= 0:
        raise PlanRefused("S1", "The stop must be on the losing side of entry")
    check_stop_live(params.side, stop, ctx)
    ec = params.entry_chase if params.entry_type == "chase" else None
    # E11: past the whole band, not just its worst edge.
    if ec is not None and ((ec.low if params.side == "buy" else ec.high) - stop) * sign <= 0:
        raise PlanRefused("E11", "The stop must be past the whole Chase band")
    if params.entry_type == "ladder" and (ladder_furthest(params, ctx.tick) - stop) * sign <= 0:
        raise PlanRefused("EL2", "The stop must be past the furthest rung")
    et = params.entry_trail
    act = et.activation if params.entry_type == "trail" and et is not None else None
    if act is not None and (act - stop) * sign <= 0:
        raise PlanRefused("E9", "The Activation is past the stop")
    size = plan_size(params, ctx, entry=entry, stop=stop)
    rungs: tuple[Rung, ...] = ()
    if params.entry_type == "ladder":
        rungs = tuple(
            ladder_rungs(
                params,
                size=size,
                tick=ctx.tick,
                qty_step=ctx.qty_step,
                min_qty=max(ctx.min_base, ctx.qty_step),
                min_quote=ctx.min_quote,
            )
        )
        # EL4: the venue counts every resting order on the Market against one limit.
        if ctx.resting_orders + len(rungs) > MARKET_ORDER_CAP:
            raise PlanRefused(
                "EL4",
                f"{len(rungs)} rungs and the {ctx.resting_orders} orders resting on this Market "
                f"are over the venue's {MARKET_ORDER_CAP}",
            )
    plan = price_plan(
        side=params.side,
        entry=entry,
        stop=stop,
        size=size,
        targets=params.targets,
        ctx=ctx,
        risk_pct=params.risk_pct,
        stop_steps=params.stop_steps,
        trail_stop=params.trail_stop,
    )
    check_targets_live(plan, ctx)
    check_trail_stop(params.trail_stop, plan, ctx)
    return dataclasses.replace(plan, rungs=rungs) if rungs else plan


def check_trail_stop(ts: TrailStop | None, plan: Plan, ctx: MarketContext) -> None:
    """M10 at start: a distance of two ticks or more, and a start the plan has."""
    if ts is None:
        return
    distance, kind = trail_price_distance(ts.unit, ts.distance, plan.r)
    _check_trail_ticks(distance, kind, ctx, "M10")
    if ts.start == "target" and ts.after > len(plan.targets):
        raise PlanRefused("M10", f"There is no target {ts.after} to start trailing after")


def check_stop_live(side: Side, stop: Decimal, ctx: MarketContext) -> None:
    """S1 and S2 against where the market is now."""
    sign = _sign(side)
    if ctx.mark > 0 and (ctx.mark - stop) * sign <= 0:
        raise PlanRefused("S1", "Mark is already past the stop")
    if ctx.liq_price is not None and ctx.liq_price > 0 and (stop - ctx.liq_price) * sign <= 0:
        raise PlanRefused("S2", "The stop is beyond the Liquidation price")


def check_targets_live(plan: Plan, ctx: MarketContext) -> None:
    sign = _sign(plan.side)
    if ctx.mark <= 0:
        return
    for t in plan.targets:
        if (t.price - ctx.mark) * sign <= 0:
            raise PlanRefused("S1", f"Mark is already past target {fmt_decimal(t.price)}")
