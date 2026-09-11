from __future__ import annotations

import random
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from typing import Any, Literal

from mayedge.algos.ladder.config import (
    DEFAULT_WINDOW,
    MAX_RUNGS,
    MAX_VAR_PCT,
    MAX_WINDOW,
    MIN_RUNGS,
    SKEW_STRENGTH,
)
from mayedge.numbers import fmt_decimal

ALGO_ID = "ladder"
ALGO_VERSION = "1"

Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class Rung:
    index: int
    price: Decimal
    qty: Decimal


@dataclass
class LadderParams:
    side: Side
    qty: Decimal
    price_from: Decimal
    price_to: Decimal
    rungs: int
    window: int = DEFAULT_WINDOW
    size_var_pct: Decimal = Decimal("0")
    price_var_pct: Decimal = Decimal("0")
    size_skew: Decimal = Decimal("0")
    rung_list: list[Rung] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "side": self.side,
            "qty": fmt_decimal(self.qty) or "0",
            "price_from": fmt_decimal(self.price_from) or "0",
            "price_to": fmt_decimal(self.price_to) or "0",
            "rungs": self.rungs,
            "window": self.window,
            "size_var_pct": fmt_decimal(self.size_var_pct) or "0",
            "price_var_pct": fmt_decimal(self.price_var_pct) or "0",
            "size_skew": fmt_decimal(self.size_skew) or "0",
            "rung_list": [
                {
                    "index": r.index,
                    "price": fmt_decimal(r.price) or "0",
                    "qty": fmt_decimal(r.qty) or "0",
                }
                for r in self.rung_list
            ],
        }

    @classmethod
    def from_json(
        cls,
        raw: dict[str, Any],
        *,
        side: Side,
        qty: Decimal,
        price_from: Decimal,
        price_to: Decimal,
        rungs: int,
        window: int,
    ) -> LadderParams:
        stored = raw.get("rung_list") or []
        rung_list: list[Rung] = []
        if isinstance(stored, list) and stored:
            for item in stored:
                if not isinstance(item, dict):
                    continue
                rung_list.append(
                    Rung(
                        index=int(item.get("index") or 0),
                        price=Decimal(str(item.get("price") or "0")),
                        qty=Decimal(str(item.get("qty") or "0")),
                    )
                )
        return cls(
            side=side,
            qty=qty,
            price_from=price_from,
            price_to=price_to,
            rungs=rungs,
            window=window,
            size_var_pct=Decimal(str(raw.get("size_var_pct") or "0")),
            price_var_pct=Decimal(str(raw.get("price_var_pct") or "0")),
            size_skew=Decimal(str(raw.get("size_skew") or "0")),
            rung_list=rung_list,
        )


def _round_to_tick(price: Decimal, tick: Decimal, side: Side) -> Decimal:
    if tick <= 0:
        raise ValueError("tick must be positive")
    steps = price / tick
    if side == "buy":
        n = steps.to_integral_value(rounding=ROUND_DOWN)
    else:
        n = steps.to_integral_value(rounding=ROUND_UP)
    return n * tick


def _round_qty(qty: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return qty
    n = (qty / step).to_integral_value(rounding=ROUND_DOWN)
    return n * step


def _var_frac(pct: Decimal) -> Decimal:
    if pct < 0 or pct > MAX_VAR_PCT:
        raise ValueError(f"Variance 0–{MAX_VAR_PCT}%")
    return pct / Decimal("100")


class NumericLcg:
    """32-bit LCG shared with the ticket preview (`createLadderRng`)."""

    def __init__(self, seed: int) -> None:
        self._state = int(seed) & 0xFFFFFFFF

    def random(self) -> float:
        self._state = (1664525 * self._state + 1013904223) & 0xFFFFFFFF
        return self._state / 4294967296.0

    def uniform(self, a: float, b: float) -> float:
        return a + (b - a) * self.random()


def _clamp_skew(skew: Decimal) -> Decimal:
    if skew < Decimal("-1") or skew > Decimal("1"):
        raise ValueError("Skew must be even, low, or high")
    return skew


def _size_weights(
    prices: list[Decimal],
    *,
    skew: Decimal,
    var_frac: Decimal,
    rng: random.Random | NumericLcg | None,
) -> list[Decimal]:
    n = len(prices)
    if n <= 0:
        return []
    lo = min(prices)
    hi = max(prices)
    span = hi - lo
    strength = abs(skew) * Decimal(str(SKEW_STRENGTH))
    raw: list[Decimal] = []
    for p in prices:
        t = Decimal("0.5") if span == 0 else (p - lo) / span
        toward_high = t if skew >= 0 else Decimal("1") - t
        w = (Decimal("1") - strength) + (Decimal("2") * strength * toward_high)
        if var_frac > 0 and rng is not None:
            u = Decimal(str(rng.uniform(float(-var_frac), float(var_frac))))
            w *= max(Decimal("0.05"), Decimal("1") + u)
        raw.append(max(Decimal("0.05"), w))
    total = sum(raw, Decimal("0"))
    if total <= 0:
        return [Decimal("1") / Decimal(n)] * n
    return [w / total for w in raw]


def _gap_weights(n: int, var_frac: Decimal, rng: random.Random | NumericLcg | None) -> list[Decimal]:
    if n <= 0:
        return []
    if var_frac <= 0 or rng is None:
        return [Decimal("1") / Decimal(n)] * n
    raw: list[Decimal] = []
    for _ in range(n):
        u = Decimal(str(rng.uniform(float(-var_frac), float(var_frac))))
        raw.append(max(Decimal("0.05"), Decimal("1") + u))
    total = sum(raw, Decimal("0"))
    if total <= 0:
        return [Decimal("1") / Decimal(n)] * n
    return [w / total for w in raw]


def _price_points(
    *,
    price_from: Decimal,
    price_to: Decimal,
    count: int,
    var_frac: Decimal,
    rng: random.Random | NumericLcg | None,
) -> list[Decimal]:
    if count <= 1:
        return [price_from]
    gaps = _gap_weights(count - 1, var_frac, rng)
    signed_span = price_to - price_from
    out = [price_from]
    acc = Decimal("0")
    last = len(gaps) - 1
    for i, w in enumerate(gaps):
        acc += w
        out.append(price_to if i == last else price_from + signed_span * acc)
    return out


def build_rungs(
    *,
    side: Side,
    qty: Decimal,
    price_from: Decimal,
    price_to: Decimal,
    rungs: int,
    tick: Decimal,
    qty_step: Decimal,
    min_qty: Decimal,
    size_var_pct: Decimal = Decimal("0"),
    price_var_pct: Decimal = Decimal("0"),
    size_skew: Decimal = Decimal("0"),
    rng: random.Random | NumericLcg | None = None,
) -> list[Rung]:
    if side not in ("buy", "sell"):
        raise ValueError("side must be buy or sell")
    if qty <= 0:
        raise ValueError("Size must be > 0")
    if rungs < MIN_RUNGS or rungs > MAX_RUNGS:
        raise ValueError(f"Orders {MIN_RUNGS}–{MAX_RUNGS}")
    if price_from <= 0 or price_to <= 0:
        raise ValueError("Set price range")
    if side == "buy" and price_from <= price_to:
        raise ValueError("Buy ladder: from price must be above to price")
    if side == "sell" and price_from >= price_to:
        raise ValueError("Sell ladder: from price must be below to price")

    size_frac = _var_frac(size_var_pct)
    price_frac = _var_frac(price_var_pct)
    skew = _clamp_skew(size_skew)
    even = _round_qty(qty / Decimal(rungs), qty_step)
    if even <= 0:
        raise ValueError("Too many orders for size")
    if min_qty > 0 and even < min_qty:
        raise ValueError(
            f"Each order must be ≥ {fmt_decimal(min_qty)} — use fewer orders or more size"
        )
    if (size_frac > 0 or price_frac > 0) and rng is None:
        rng = NumericLcg(int(random.Random().randrange(0, 2**32)))

    unique: list[Decimal] = []
    seen: set[Decimal] = set()
    for raw_price in _price_points(
        price_from=price_from,
        price_to=price_to,
        count=rungs,
        var_frac=price_frac,
        rng=rng,
    ):
        price = _round_to_tick(raw_price, tick, side)
        if price in seen:
            continue
        seen.add(price)
        unique.append(price)
    if not unique:
        raise ValueError("No valid orders after tick alignment")

    weights = _size_weights(unique, skew=skew, var_frac=size_frac, rng=rng)
    out: list[Rung] = []
    allocated = Decimal("0")
    last = len(unique) - 1
    for i, price in enumerate(unique):
        if i == last:
            rung_qty = _round_qty(qty - allocated, qty_step)
        else:
            rung_qty = _round_qty(qty * weights[i], qty_step)
        if rung_qty <= 0:
            continue
        if min_qty > 0 and rung_qty < min_qty:
            raise ValueError(
                f"Each order must be ≥ {fmt_decimal(min_qty)} — use fewer orders or more size"
            )
        allocated += rung_qty
        out.append(Rung(index=len(out), price=price, qty=rung_qty))

    if not out:
        raise ValueError("Too many orders for size")
    remainder = qty - sum(r.qty for r in out)
    if remainder != 0 and out:
        last_rung = out[-1]
        patched = last_rung.qty + remainder
        if patched <= 0:
            raise ValueError("Too many orders for size")
        if min_qty > 0 and patched < min_qty:
            raise ValueError(
                f"Each order must be ≥ {fmt_decimal(min_qty)} — use fewer orders or more size"
            )
        out[-1] = Rung(index=last_rung.index, price=last_rung.price, qty=patched)
    return out


def validate_params(
    p: LadderParams,
    *,
    tick: Decimal,
    qty_step: Decimal,
    min_qty: Decimal,
    rng: random.Random | NumericLcg | None = None,
) -> None:
    if p.window < 1 or p.window > MAX_WINDOW:
        raise ValueError(f"Live window 1–{MAX_WINDOW}")
    p.rung_list = build_rungs(
        side=p.side,
        qty=p.qty,
        price_from=p.price_from,
        price_to=p.price_to,
        rungs=p.rungs,
        tick=tick,
        qty_step=qty_step,
        min_qty=min_qty,
        size_var_pct=p.size_var_pct,
        price_var_pct=p.price_var_pct,
        size_skew=p.size_skew,
        rng=rng,
    )


def is_passive(*, side: Side, price: Decimal, bid: Decimal | None, ask: Decimal | None) -> bool:
    if side == "buy":
        if ask is None or ask <= 0:
            return True
        return price < ask
    if bid is None or bid <= 0:
        return True
    return price > bid


def sort_by_closeness(rungs: list[Rung], side: Side) -> list[Rung]:
    if side == "buy":
        return sorted(rungs, key=lambda r: r.price, reverse=True)
    return sorted(rungs, key=lambda r: r.price)


def _price_to_index(params: LadderParams) -> dict[Decimal, int]:
    return {r.price: r.index for r in params.rung_list}


def live_rung_indices(params: LadderParams, ledger: Any) -> set[int]:
    by_price = _price_to_index(params)
    out: set[int] = set()
    for clip in ledger.live_clips():
        idx = by_price.get(Decimal(str(clip.price)))
        if idx is not None:
            out.add(idx)
    return out


def filled_rung_indices(params: LadderParams, ledger: Any) -> set[int]:
    by_price = _price_to_index(params)
    out: set[int] = set()
    for clip in ledger.clips:
        if clip.status != "filled":
            continue
        idx = by_price.get(Decimal(str(clip.price)))
        if idx is not None:
            out.add(idx)
    return out


def select_rungs_to_place(
    params: LadderParams,
    *,
    ledger: Any,
    live_count: int,
    bid: Decimal | None,
    ask: Decimal | None,
) -> list[Rung]:
    need = max(0, params.window - live_count)
    if need <= 0:
        return []
    excluded = live_rung_indices(params, ledger) | filled_rung_indices(params, ledger)
    pending = [r for r in params.rung_list if r.index not in excluded]
    passive = [
        r
        for r in pending
        if is_passive(side=params.side, price=r.price, bid=bid, ask=ask)
    ]
    ordered = sort_by_closeness(passive, params.side)
    return ordered[:need]
