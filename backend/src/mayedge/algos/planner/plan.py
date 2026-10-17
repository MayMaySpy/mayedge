"""Planner plan math. Pure: no venue, no clock. Rule ids are docs/planner-rules.md."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from typing import Any, Literal

from mayedge.algos.planner.config import DEFAULT_SLIPPAGE, MAX_SLIPPAGE, MAX_TARGETS
from mayedge.numbers import fmt_decimal, parse_decimal

ALGO_ID = "planner"
ALGO_VERSION = "1"

Side = Literal["buy", "sell"]
Mode = Literal["enter", "attach"]
EntryType = Literal["market", "limit"]
TargetKind = Literal["price", "r"]

HUNDRED = Decimal("100")
BPS = Decimal("10000")


class PlanRefused(ValueError):
    """A plan that breaks a rule. ``rule`` is its id in planner-rules.md."""

    def __init__(self, rule: str, message: str) -> None:
        super().__init__(message)
        self.rule = rule
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"rule": self.rule, "message": self.message}


@dataclass(frozen=True)
class Target:
    kind: TargetKind
    value: Decimal
    pct: Decimal

    def to_json(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "value": fmt_decimal(self.value) or "0",
            "pct": fmt_decimal(self.pct) or "0",
        }

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
        return cls(kind=kind, value=value, pct=pct)


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
    breakeven: bool = True
    expiry_min: int | None = None
    slippage: float = DEFAULT_SLIPPAGE

    def to_json(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "side": self.side,
            "stop": fmt_decimal(self.stop) or "0",
            "targets": [t.to_json() for t in self.targets],
            "entry_type": self.entry_type,
            "entry_price": fmt_decimal(self.entry_price),
            "size": fmt_decimal(self.size),
            "risk_pct": fmt_decimal(self.risk_pct),
            "breakeven": self.breakeven,
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
        if entry_type not in ("market", "limit"):
            raise ValueError("entry_type must be market or limit")
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
            breakeven=bool(raw.get("breakeven", True)),
            expiry_min=int(expiry) if expiry not in (None, "", 0, "0") else None,
            slippage=_clamp_slippage(raw.get("slippage")),
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


@dataclass(frozen=True)
class PlannedTarget:
    index: int
    price: Decimal
    qty: Decimal
    pct: Decimal
    r: Decimal
    move_pct: Decimal

    def to_json(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "price": fmt_decimal(self.price) or "0",
            "qty": fmt_decimal(self.qty) or "0",
            "pct": fmt_decimal(self.pct) or "0",
            "r": fmt_decimal(self.r) or "0",
            "move_pct": fmt_decimal(self.move_pct) or "0",
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
        )


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
        )


def _opt_decimal(raw: object) -> Decimal | None:
    if raw is None or raw == "":
        return None
    return parse_decimal(str(raw))


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
    if params.entry_price is None or params.entry_price <= 0:
        raise PlanRefused("S1", "Set the Limit entry price")
    # A buy rests at or below what was typed, a sell at or above.
    return round_price(params.entry_price, ctx.tick, up=params.side == "sell")


def _check_targets_shape(targets: list[Target]) -> None:
    if not targets:
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


def _target_prices(
    side: Side, entry: Decimal, r: Decimal, targets: list[Target], tick: Decimal
) -> list[tuple[Decimal, Decimal]]:
    """(price, pct) per target, P4 and P6, nearest entry first."""
    out: list[tuple[Decimal, Decimal]] = []
    sign = _sign(side)
    for t in targets:
        raw = entry + sign * r * t.value if t.kind == "r" else t.value
        # Targets round toward entry.
        out.append((round_price(raw, tick, up=side == "sell"), t.pct))
    out.sort(key=lambda pt: pt[0] * sign)
    return out


def _size_targets(
    priced: list[tuple[Decimal, Decimal]],
    *,
    size: Decimal,
    qty_step: Decimal,
    min_qty: Decimal,
) -> tuple[list[tuple[Decimal, Decimal, Decimal]], list[str]]:
    """(price, pct, qty) per target. P5 Runner, P6 rounding, P7 merges."""
    legs = list(priced)
    warnings: list[str] = []
    while legs:
        total_pct = sum((pct for _, pct in legs), Decimal("0"))
        closing = round_qty(size * total_pct / HUNDRED, qty_step)
        sized: list[tuple[Decimal, Decimal, Decimal]] = []
        used = Decimal("0")
        for i, (price, pct) in enumerate(legs):
            if i == len(legs) - 1:
                qty = closing - used
            else:
                qty = round_qty(size * pct / HUNDRED, qty_step)
            used += qty
            sized.append((price, pct, qty))
        small = next((i for i, leg in enumerate(sized) if leg[2] <= 0 or leg[2] < min_qty), None)
        if small is None:
            return sized, warnings
        if len(legs) == 1:
            break
        price, pct = legs.pop(small)
        into = small if small < len(legs) else small - 1
        keep_price, keep_pct = legs[into]
        legs[into] = (keep_price, keep_pct + pct)
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
) -> Plan:
    """Draw a plan at a known entry and size. The job calls this again after the fill."""
    _check_targets_shape(targets)
    stop = stop_price(side, stop, ctx.tick)
    sign = _sign(side)
    if (entry - stop) * sign <= 0:
        raise PlanRefused("S1", "The stop is on the winning side of entry")
    r = abs(entry - stop)
    priced = _target_prices(side, entry, r, targets, ctx.tick)
    for price, _ in priced:
        if (price - entry) * sign <= 0:
            raise PlanRefused("S1", f"Target {fmt_decimal(price)} is not past entry")
    if size <= 0:
        raise PlanRefused("P2", "Size is 0")
    sized, warnings = _size_targets(
        priced, size=size, qty_step=ctx.qty_step, min_qty=ctx.min_qty
    )
    planned = tuple(
        PlannedTarget(
            index=i + 1,
            price=price,
            qty=qty,
            pct=pct,
            r=(abs(price - entry) / r) if r > 0 else Decimal("0"),
            move_pct=_move_pct(side, entry, price),
        )
        for i, (price, pct, qty) in enumerate(sized)
    )
    closing = sum((t.qty for t in planned), Decimal("0"))
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
        breakeven=breakeven_price(side, entry, taker_bps=ctx.taker_bps, tick=ctx.tick),
        stop_pct=_move_pct(side, entry, stop),
        warnings=tuple(warnings),
    )


def _plan_size(params: PlannerParams, ctx: MarketContext, *, entry: Decimal, stop: Decimal) -> Decimal:
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
    size = _plan_size(params, ctx, entry=entry, stop=stop)
    plan = price_plan(
        side=params.side,
        entry=entry,
        stop=stop,
        size=size,
        targets=params.targets,
        ctx=ctx,
        risk_pct=params.risk_pct,
    )
    check_targets_live(plan, ctx)
    return plan


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
