"""Classify composite alert episodes into trader-facing setup labels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SETUP_LABELS: dict[str, str] = {
    "breakout_longs": "Breakout: longs opening",
    "short_squeeze": "Short squeeze",
    "breakdown_shorts": "Breakdown: shorts opening",
    "long_flush": "Long flush",
    "pump": "Sharp move up",
    "dump": "Sharp move down",
    "vol_surge": "Volume surge",
    "absorption": "Absorption",
    "crowded_longs": "Crowded longs",
    "crowded_shorts": "Crowded shorts",
    "mark_off_book": "Mark off book",
    "liq_cascade": "Liquidation cascade",
    "mixed": "Unusual activity",
}

# |5m move| under this many sigma counts as "price did not move".
_FLAT_SIGMA = 1.0


@dataclass(frozen=True)
class FactorView:
    kind: str
    direction: str
    value: float
    score: float
    window: str = ""


@dataclass(frozen=True)
class PriceContext:
    """The 5m move whether or not it crossed the price threshold."""

    move_pct: float
    move_sigma: float

    @property
    def direction(self) -> str:
        if self.move_sigma >= _FLAT_SIGMA and self.move_pct > 0:
            return "up"
        if self.move_sigma >= _FLAT_SIGMA and self.move_pct < 0:
            return "down"
        return "flat"


def classify_setup(factors: list[FactorView], context: PriceContext | None = None) -> str:
    by_kind = {f.kind: f for f in factors}
    price = by_kind.get("price")
    oi = by_kind.get("oi")
    vol = by_kind.get("volume")
    liq = by_kind.get("liq_cluster")
    prem = by_kind.get("premium")
    fund = by_kind.get("funding")
    disloc = by_kind.get("dislocation")

    px_dir = price.direction if price else (context.direction if context else "flat")

    if liq:
        if px_dir == "down" or liq.direction == "down":
            return "long_flush"
        if px_dir == "up" or liq.direction == "up":
            return "short_squeeze"
        return "liq_cascade"

    if price and oi:
        if px_dir == "up":
            return "breakout_longs" if oi.direction == "up" else "short_squeeze"
        if px_dir == "down":
            return "breakdown_shorts" if oi.direction == "up" else "long_flush"

    if price:
        return "pump" if px_dir == "up" else "dump"

    if vol:
        if context is not None and context.direction == "flat":
            return "absorption"
        return "vol_surge"

    if prem or fund:
        lean = (prem.value if prem else 0.0) + (fund.value * 10 if fund else 0.0)
        if lean > 0:
            return "crowded_longs"
        if lean < 0:
            return "crowded_shorts"

    if disloc:
        return "mark_off_book"

    if oi:
        return "breakout_longs" if px_dir == "up" else "mixed"

    return "mixed"


def setup_direction(factors: list[FactorView], context: PriceContext | None) -> str:
    for kind in ("price", "liq_cluster"):
        for f in factors:
            if f.kind == kind and f.direction in ("up", "down"):
                return f.direction
    if context is not None and context.direction != "flat":
        return context.direction
    for kind in ("oi", "premium", "dislocation"):
        for f in factors:
            if f.kind == kind and f.direction in ("up", "down"):
                return f.direction
    return "flat"


def _usd(v: float) -> str:
    a = abs(v)
    if a >= 1_000_000:
        return f"${v / 1_000_000:.1f}M"
    if a >= 1_000:
        return f"${v / 1_000:.0f}k"
    return f"${v:.0f}"


def format_factor(f: dict[str, Any]) -> str:
    kind = str(f.get("kind") or "")
    value = float(f.get("value") or 0)
    if kind == "volume":
        return f"Vol {value:.1f}×"
    if kind == "price":
        return f"Px {value:+.2f}%"
    if kind == "oi":
        return f"OI {value:+.1f}%"
    if kind == "premium":
        return f"Prem {value:+.2f}%"
    if kind == "dislocation":
        return f"Off mark {value:.0f}bp"
    if kind == "funding":
        return f"Fund {value:+.4f}%/h"
    if kind == "liq_cluster":
        return f"Liqs {_usd(value)}"
    return kind


def build_note(setup_key: str, factors: list[dict[str, Any]]) -> str:
    label = SETUP_LABELS.get(setup_key, setup_key)
    parts = [format_factor(f) for f in factors[:3]]
    return f"{label} · " + " · ".join(parts) if parts else label
