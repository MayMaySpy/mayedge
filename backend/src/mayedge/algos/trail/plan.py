"""Trail inputs and start checks. Pure: no venue, no clock. Rule ids are docs/trail-rules.md."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from mayedge.algos.planner.plan import MarketContext, round_qty
from mayedge.algos.trail import engine
from mayedge.algos.trail.config import DEFAULT_SLIPPAGE, MAX_SLIPPAGE, MIN_DISTANCE_TICKS
from mayedge.algos.trail.engine import DistanceKind, Follow, Side
from mayedge.numbers import fmt_decimal, parse_decimal

ALGO_ID = "trail"
ALGO_VERSION = "1"

Kind = Literal["entry", "stop", "tp"]
Reference = Literal["mark", "last"]

HUNDRED = Decimal("100")
KIND_NAMES: dict[str, str] = {
    "entry": "Trail Entry",
    "stop": "Trail Stop",
    "tp": "Trail Take Profit",
}


class TrailRefused(ValueError):
    """A Trail that breaks a rule. ``rule`` is its id in trail-rules.md."""

    def __init__(self, rule: str, message: str) -> None:
        super().__init__(message)
        self.rule = rule
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"rule": self.rule, "message": self.message}


@dataclass
class TrailParams:
    kind: Kind
    distance: Decimal
    distance_kind: DistanceKind
    # The side of the order it fires. For a Stop or Take Profit, set from the Position.
    side: Side | None = None
    reference: Reference = "mark"
    activation: Decimal | None = None
    start: Decimal | None = None
    size: Decimal | None = None
    size_pct: Decimal | None = None
    expiry_min: int | None = None
    slippage: float = DEFAULT_SLIPPAGE

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "side": self.side,
            "distance": fmt_decimal(self.distance) or "0",
            "distance_kind": self.distance_kind,
            "reference": self.reference,
            "activation": fmt_decimal(self.activation),
            "start": fmt_decimal(self.start),
            "size": fmt_decimal(self.size),
            "size_pct": fmt_decimal(self.size_pct),
            "expiry_min": self.expiry_min,
            "slippage": self.slippage,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> TrailParams:
        """Parse a start body or a stored row. Shape errors refuse; rules are check_start's."""
        kind = raw.get("kind")
        if kind not in ("entry", "stop", "tp"):
            raise ValueError("kind must be entry, stop or tp")
        side = raw.get("side") or None
        if side not in (None, "buy", "sell"):
            raise ValueError("side must be buy or sell")
        distance_kind = raw.get("distance_kind") or "pct"
        if distance_kind not in ("pct", "price"):
            raise ValueError("distance_kind must be pct or price")
        reference = raw.get("reference") or "mark"
        if reference not in ("mark", "last"):
            raise ValueError("reference must be mark or last")
        try:
            distance = parse_decimal(str(raw.get("distance") or ""))
        except ValueError:
            raise TrailRefused("S3", "Set a distance") from None
        expiry = raw.get("expiry_min")
        return cls(
            kind=kind,
            side=side,
            distance=distance,
            distance_kind=distance_kind,
            reference=reference,
            activation=_opt_decimal(raw.get("activation")),
            start=_opt_decimal(raw.get("start")),
            size=_opt_decimal(raw.get("size")),
            size_pct=_opt_decimal(raw.get("size_pct")),
            expiry_min=int(expiry) if expiry not in (None, "", 0, "0") else None,
            slippage=_clamp_slippage(raw.get("slippage")),
        )


@dataclass(frozen=True)
class Resolved:
    """What a Trail sends, drawn at start."""

    side: Side
    # Entry: its size. Take Profit: its share of the Position. Stop: 0, tied to the Position.
    qty: Decimal
    follow: Follow
    # Where a Stop's venue order goes on at start (TS1). None for Entry and Take Profit.
    start: Decimal | None
    mark: Decimal

    def to_json(self) -> dict[str, Any]:
        return {
            "side": self.side,
            "qty": fmt_decimal(self.qty) or "0",
            "start": fmt_decimal(self.start),
            "activation": fmt_decimal(self.follow.activation),
            "mark": fmt_decimal(self.mark),
            "step": fmt_decimal(engine.step(self.follow, self.mark)),
            # What the trigger would be if the best price were mark now.
            "trigger_now": fmt_decimal(engine.trigger_at(self.follow, self.mark)),
        }


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


def follow_of(params: TrailParams, side: Side, tick: Decimal, *, floor: Decimal | None) -> Follow:
    return Follow(
        side=side,
        distance=params.distance,
        distance_kind=params.distance_kind,
        tick=tick,
        activation=params.activation,
        floor=floor,
    )


def check_distance(params: TrailParams, ctx: MarketContext) -> None:
    """S3: at least two ticks at today's price."""
    if params.distance <= 0:
        raise TrailRefused("S3", "The distance must be above 0")
    if params.distance_kind == "pct" and params.distance >= HUNDRED:
        raise TrailRefused("S3", "The distance must be under 100%")
    at = ctx.mark * params.distance / HUNDRED if params.distance_kind == "pct" else params.distance
    if ctx.tick > 0 and at < ctx.tick * MIN_DISTANCE_TICKS:
        raise TrailRefused("S3", f"The distance is under {MIN_DISTANCE_TICKS} ticks")


def check_start(params: TrailParams, ctx: MarketContext) -> Resolved:
    """S3 and the kind's start rules (TS1, TT1, TT2). Returns what the job sends."""
    if ctx.mark <= 0:
        raise TrailRefused("S3", "No mark to start from")
    check_distance(params, ctx)
    if params.kind == "entry":
        return _check_entry(params, ctx)
    if ctx.position_size == 0:
        raise TrailRefused("TS1" if params.kind == "stop" else "TT1", "No open Position")
    side: Side = "sell" if ctx.position_size > 0 else "buy"
    if params.side is not None and params.side != side:
        raise TrailRefused("S3", "The side is not the Position's closing side")
    if params.kind == "stop":
        return _check_stop(params, ctx, side)
    return _check_tp(params, ctx, side)


def _check_activation(f: Follow, ctx: MarketContext, *, required: bool) -> None:
    if f.activation is None:
        if required:
            raise TrailRefused("TT1", "Set the Activation price")
        return
    if f.activation <= 0:
        raise TrailRefused("S3", "The Activation must be above 0")
    if engine.reached(f, ctx.mark, f.activation):
        raise TrailRefused("S3", "Mark is already past the Activation")


def _check_entry(params: TrailParams, ctx: MarketContext) -> Resolved:
    if params.side is None:
        raise TrailRefused("S3", "Set Buy or Sell")
    if params.size is None or params.size <= 0:
        raise TrailRefused("S3", "Set a size")
    qty = round_qty(params.size, ctx.qty_step)
    if qty <= 0 or qty < ctx.min_qty:
        raise TrailRefused("S3", f"Size is below the venue minimum {fmt_decimal(ctx.min_qty)}")
    f = follow_of(params, params.side, ctx.tick, floor=None)
    _check_activation(f, ctx, required=False)
    return Resolved(side=params.side, qty=qty, follow=f, start=None, mark=ctx.mark)


def _check_stop(params: TrailParams, ctx: MarketContext, side: Side) -> Resolved:
    bare = follow_of(params, side, ctx.tick, floor=None)
    start = (
        engine.round_away(bare, params.start) if params.start else engine.trigger_at(bare, ctx.mark)
    )
    if start <= 0:
        raise TrailRefused("S3", "The start is below 0")
    # A sell stop sits below mark, a buy stop above it.
    if not engine.better(bare, ctx.mark, start):
        raise TrailRefused("S3", "The start is on the wrong side of mark")
    if (
        ctx.liq_price is not None
        and ctx.liq_price > 0
        and not engine.better(bare, start, ctx.liq_price)
    ):
        raise TrailRefused("S3", "The start is beyond the Liquidation price")
    f = follow_of(params, side, ctx.tick, floor=start)
    _check_activation(f, ctx, required=False)
    return Resolved(side=side, qty=Decimal("0"), follow=f, start=start, mark=ctx.mark)


def _check_tp(params: TrailParams, ctx: MarketContext, side: Side) -> Resolved:
    pct = params.size_pct if params.size_pct is not None else HUNDRED
    if pct <= 0 or pct > HUNDRED:
        raise TrailRefused("TT2", "Size % is between 0 and 100")
    qty = round_qty(abs(ctx.position_size) * pct / HUNDRED, ctx.qty_step)
    if qty <= 0 or qty < ctx.min_qty:
        raise TrailRefused("TT2", f"Size is below the venue minimum {fmt_decimal(ctx.min_qty)}")
    f = follow_of(params, side, ctx.tick, floor=None)
    _check_activation(f, ctx, required=True)
    return Resolved(side=side, qty=qty, follow=f, start=None, mark=ctx.mark)
