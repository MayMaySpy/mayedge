from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

ALGO_ID = "advanced-twap"
ALGO_VERSION = "1"
FREQ_JITTER = Decimal("0.40")
SIZE_JITTER = Decimal("0.30")
MIN_FREQ_SEC = 2
MAX_FREQ_SEC = 3_600
MIN_DURATION_SEC = 60
MAX_DURATION_SEC = 2_592_000
TWAP_COI_BASE = 7_000_000_000
TWAP_COI_END = 8_000_000_000

Style = Literal["passive", "neutral", "aggressive"]
Side = Literal["buy", "sell"]
STYLES: tuple[Style, ...] = ("passive", "neutral", "aggressive")


@dataclass
class AdvancedTwapParams:
    side: Side
    qty: Decimal
    duration_seconds: int
    frequency_seconds: int = 5
    style: Style = "neutral"
    randomize: bool = True
    max_price: Decimal | None = None
    max_index_pct: Decimal | None = None
    started_at: int = 0
    deadline_at: int = 0
    slices_done: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "side": self.side,
            "qty": str(self.qty),
            "duration_seconds": self.duration_seconds,
            "frequency_seconds": self.frequency_seconds,
            "style": self.style,
            "randomize": self.randomize,
            "max_price": str(self.max_price) if self.max_price is not None else None,
            "max_index_pct": str(self.max_index_pct) if self.max_index_pct is not None else None,
            "started_at": self.started_at,
            "deadline_at": self.deadline_at,
            "slices_done": self.slices_done,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any], *, side: Side, qty: Decimal) -> AdvancedTwapParams:
        style = raw.get("style") or "neutral"
        if style not in STYLES:
            style = "neutral"
        freq = int(raw.get("frequency_seconds") or 5)
        duration = int(raw.get("duration_seconds") or 0)
        max_price = raw.get("max_price")
        max_index = raw.get("max_index_pct")
        return cls(
            side=side,
            qty=qty,
            duration_seconds=duration,
            frequency_seconds=freq,
            style=style,
            randomize=bool(raw.get("randomize", True)),
            max_price=Decimal(str(max_price)) if max_price not in (None, "") else None,
            max_index_pct=Decimal(str(max_index)) if max_index not in (None, "") else None,
            started_at=int(raw.get("started_at") or 0),
            deadline_at=int(raw.get("deadline_at") or 0),
            slices_done=int(raw.get("slices_done") or 0),
        )


def validate_params(p: AdvancedTwapParams) -> None:
    if p.side not in ("buy", "sell"):
        raise ValueError("side must be buy or sell")
    if p.qty <= 0:
        raise ValueError("Size must be > 0")
    if p.duration_seconds < MIN_DURATION_SEC or p.duration_seconds > MAX_DURATION_SEC:
        raise ValueError("Running time 1m–30d")
    if p.frequency_seconds < MIN_FREQ_SEC or p.frequency_seconds > MAX_FREQ_SEC:
        raise ValueError("Slice frequency 2s–1h")
    if p.style not in STYLES:
        raise ValueError("Unknown TWAP style")
    if p.max_price is not None and p.max_price <= 0:
        raise ValueError("Max price must be > 0")
    if p.max_index_pct is not None and p.max_index_pct <= 0:
        raise ValueError("Max % past index must be > 0")


def order_count(duration_sec: int, freq_sec: int) -> int:
    if duration_sec <= 0 or freq_sec <= 0:
        return 0
    return duration_sec // freq_sec + 1


def jitter(base: Decimal, pct: Decimal, u: float) -> Decimal:
    """Map u in [0, 1] onto [base*(1-pct), base*(1+pct)]."""
    u = min(1.0, max(0.0, u))
    lo = Decimal(1) - pct
    hi = Decimal(1) + pct
    return base * (lo + (hi - lo) * Decimal(str(u)))


def next_wait_s(freq_sec: int, randomize: bool, u: float = 0.5) -> float:
    if freq_sec <= 0:
        return 0.0
    if not randomize:
        return float(freq_sec)
    return float(jitter(Decimal(freq_sec), FREQ_JITTER, u))


def slice_qty(
    remaining: Decimal,
    orders_left: int,
    *,
    randomize: bool,
    u: float = 0.5,
) -> Decimal:
    if remaining <= 0 or orders_left <= 0:
        return Decimal(0)
    if orders_left == 1:
        return remaining
    base = remaining / Decimal(orders_left)
    if randomize:
        base = jitter(base, SIZE_JITTER, u)
    if base > remaining:
        return remaining
    if base <= 0:
        return remaining
    return base


def skip_reason(
    *,
    side: Side,
    mark: Decimal | None,
    index: Decimal | None,
    max_price: Decimal | None,
    max_index_pct: Decimal | None,
) -> str | None:
    if mark is None or mark <= 0:
        return "no_mark"
    if max_price is not None and max_price > 0:
        if side == "buy" and mark > max_price:
            return "above_max_price"
        if side == "sell" and mark < max_price:
            return "below_max_price"
    if max_index_pct is not None and max_index_pct > 0 and index is not None and index > 0:
        moved = abs(mark - index) / index * Decimal(100)
        if moved > max_index_pct:
            return "past_index"
    return None


def slice_quote(
    style: Style,
    side: Side,
    *,
    bid: Decimal | None,
    ask: Decimal | None,
    mid: Decimal | None,
    mark: Decimal | None,
) -> dict[str, str | None]:
    if style == "aggressive":
        return {"kind": "market", "tif": None, "price": None}
    px = mid or mark
    if style == "neutral":
        return {"kind": "limit", "tif": "ioc", "price": str(px) if px else None}
    if side == "buy":
        park = bid or px
    else:
        park = ask or px
    return {"kind": "limit", "tif": "post_only", "price": str(park) if park else None}
