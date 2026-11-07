"""What an alert is: the snapshot it reads, the facts it states, and the rows the panel shows."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from mayedge.alert_settings import AlertSettings

NOTABLE = 2
URGENT = 3
# R4, M5: states that go on firing once they start. A Move keeps its own clock.
STATE_KINDS = frozenset({"liqs", "near_liq", "move"})
# W2: a level the price closed through. The detector raises it once a day.
RANGE_KINDS = frozenset({"week_high", "week_low", "quarter_high", "quarter_low"})
_RANGE_NAME = {
    "week_high": "week high",
    "week_low": "week low",
    "quarter_high": "quarter high",
    "quarter_low": "quarter low",
}
# R3: rules that are Urgent on any market.
_URGENT_KINDS = frozenset({"liqs", "near_liq"})
# R4: a state that keeps firing raises another row at half again its largest size.
_ESCALATE = 1.5
# How many times its Usual move a span can be said to be.
_MULTIPLE_CAP = 99.0


@dataclass
class MarketSnapshot:
    ts: float
    mark: float
    last: float
    index: float
    mid: float
    bid: float
    ask: float
    oi: float
    vol_quote: float
    funding: float
    premium: float
    day_high: float = 0.0
    day_low: float = 0.0


@dataclass(frozen=True)
class Held:
    """What the operator has on a market. No side means a working order and no Position."""

    side: str = ""
    liquidation_price: float = 0.0


def order_away_pct(
    *, side: str, price: float, trigger: float, last: float | None, mark: float | None
) -> float | None:
    """H1. How far a working order is from filling, in percent. None when there is no price.

    A limit is measured from the last trade (mark when there is none), and is 0 once through.
    A Stop or Take Profit is measured from mark to its trigger.
    """
    if trigger > 0:
        if not mark or mark <= 0:
            return None
        return abs(mark - trigger) / mark * 100.0
    ref = last if last and last > 0 else mark
    if not ref or ref <= 0 or price <= 0:
        return None
    if side == "buy":
        return 0.0 if price >= ref else (ref - price) / ref * 100.0
    return 0.0 if price <= ref else (price - ref) / ref * 100.0


@dataclass
class Fact:
    """One thing a row states. A rule that fired has a size; what the tape showed has none."""

    kind: str
    direction: str
    value: float
    unit: str
    window: str = ""
    size: float | None = None
    detail: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "kind": self.kind,
            "direction": self.direction,
            "value": self.value,
            "unit": self.unit,
        }
        if self.window:
            row["window"] = self.window
        if self.size is not None:
            row["size"] = round(self.size, 2)
        for key, value in self.detail.items():
            row[key] = round(value, 4)
        return row


@dataclass
class AlertEvent:
    id: str
    ts: int
    symbol: str
    market_index: int
    rule: str
    severity: int
    direction: str
    size: float
    price: float
    facts: list[dict[str, Any]]
    held: str
    started_at: int
    note: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts,
            "symbol": self.symbol,
            "market_index": self.market_index,
            "rule": self.rule,
            "severity": self.severity,
            "direction": self.direction,
            "size": round(self.size, 2),
            "price": self.price,
            "facts": self.facts,
            "held": self.held,
            "started_at": self.started_at,
            "note": self.note,
        }


def _usd(v: float) -> str:
    a = abs(v)
    if a >= 1_000_000:
        return f"${a / 1_000_000:.1f}M"
    if a >= 1_000:
        return f"${a / 1_000:.0f}k"
    return f"${a:.0f}"


def _px(value: float) -> str:
    text = f"{value:.8f}".rstrip("0").rstrip(".")
    return text or "0"


def describe(fact: Fact) -> str:
    """The fact in plain words, for the note and a push. No label says what it means."""
    v = fact.value
    if fact.kind == "move":
        text = f"{v:+.2f}% in {fact.window or '1m'}"
        multiple = fact.detail.get("multiple")
        if fact.size is not None and multiple is not None:
            text += f" · {multiple:.0f}× its usual {fact.window or '1m'}"
        excess = fact.detail.get("excess")
        if excess is not None:
            text += f" · {excess:+.2f}% past the board"
        return text
    if fact.kind == "volume":
        return f"volume {fact.detail.get('multiple', 0.0):.0f}× ({_usd(v)})"
    if fact.kind == "oi":
        usd = fact.detail.get("usd")
        return f"OI {v:+.2f}%" + (
            "" if usd is None else f" ({'+' if usd >= 0 else '−'}{_usd(usd)})"
        )
    if fact.kind == "liqs":
        side = "longs" if fact.direction == "down" else "shorts"
        return f"{_usd(v)} {side} liquidated · {fact.detail.get('bps', 0.0):.0f} bps of OI"
    if fact.kind == "near_liq":
        return f"{v:.1f}% from liquidation"
    if fact.kind in _RANGE_NAME:
        return f"through the {_RANGE_NAME[fact.kind]} {_px(fact.value)}"
    if fact.kind == "day_high":
        return "at the day's high"
    if fact.kind == "day_low":
        return "at the day's low"
    if fact.kind == "funding":
        return f"funding {v:+.4f}%/h"
    return fact.kind


@dataclass
class _Row:
    id: str
    market_index: int
    symbol: str
    started_s: float
    price: float
    rules: dict[str, Fact]
    context: dict[str, Fact]
    held: str

    def headline(self) -> Fact:
        return max(self.rules.values(), key=lambda f: f.size or 0.0)

    def size(self) -> float:
        return self.headline().size or 0.0

    def severity(self) -> int:
        """R3. Urgent for what goes against what the operator has on (ADR 0027)."""
        if any(kind in _URGENT_KINDS for kind in self.rules):
            return URGENT
        direction = self.direction()
        if direction not in ("up", "down") or not self.held:
            return NOTABLE
        if self.held == "order":
            return URGENT
        against = (self.held == "long") == (direction == "down")
        return URGENT if against else NOTABLE

    def direction(self) -> str:
        """The largest rule that points somewhere. Volume alone points nowhere."""
        for fact in sorted(self.rules.values(), key=lambda f: -(f.size or 0.0)):
            if fact.direction in ("up", "down"):
                return fact.direction
        return "flat"

    def signature(self) -> tuple[float, str, int, int]:
        return (round(self.size(), 1), self.headline().kind, len(self.rules), self.severity())

    def take(self, fired: Iterable[Fact], context: Iterable[Fact]) -> None:
        """Each rule kept at its largest. The tape is shown only where no rule already says it."""
        for fact in fired:
            prev = self.rules.get(fact.kind)
            if prev is None or (fact.size or 0.0) > (prev.size or 0.0):
                self.rules[fact.kind] = fact
            self.context.pop(fact.kind, None)
        for fact in context:
            if fact.kind in self.rules:
                continue
            prev = self.context.get(fact.kind)
            if prev is None or abs(fact.value) > abs(prev.value):
                self.context[fact.kind] = fact


class RowBook:
    """Which fired rules are news, and which row they belong on."""

    def __init__(self, cfg: AlertSettings) -> None:
        self._cfg = cfg
        self._rows: dict[int, _Row] = {}
        self._standing: dict[tuple[int, str], tuple[float, float]] = {}
        self._new_row_times: deque[float] = deque()

    def ingest(
        self,
        market_index: int,
        symbol: str,
        fired: list[Fact],
        context: list[Fact],
        now: float,
        *,
        price: float,
        held: str = "",
    ) -> AlertEvent | None:
        row = self._rows.get(market_index)
        # R2: a row takes updates for a while, then it is final.
        if row is not None and now - row.started_s >= self._cfg.merge_s:
            row = None
        news = [fact for fact in fired if self._is_news(market_index, fact, row, now)]
        if not news:
            return None

        if row is not None:
            before = row.signature()
            row.take(news, context)
            row.held = held or row.held
            if row.signature() == before:
                return None
            return self._event(row, now)

        if not self._cap_has_room(now):
            return None
        self._new_row_times.append(now)
        row = _Row(
            id=f"alert-{market_index}-{int(now)}",
            market_index=market_index,
            symbol=symbol,
            started_s=now,
            price=price,
            rules={},
            context={},
            held=held,
        )
        row.take(news, context)
        self._rows[market_index] = row
        return self._event(row, now)

    def _is_news(self, market_index: int, fact: Fact, row: _Row | None, now: float) -> bool:
        """R4, M5: a state is news when it starts, and when it grows by half."""
        if fact.kind not in STATE_KINDS:
            return True
        key = (market_index, fact.kind)
        size = fact.size or 0.0
        quiet = self._cfg.move_quiet_s if fact.kind == "move" else self._cfg.quiet_s
        standing = self._standing.get(key)
        if standing is None or now - standing[1] >= quiet:
            self._standing[key] = (size, now)
            return True
        largest, _last = standing
        if row is not None and fact.kind in row.rules:
            self._standing[key] = (max(largest, size), now)
            return True
        if size >= largest * _ESCALATE:
            self._standing[key] = (size, now)
            return True
        self._standing[key] = (largest, now)
        return False

    def _cap_has_room(self, now: float) -> bool:
        """R6."""
        while self._new_row_times and now - self._new_row_times[0] > 60.0:
            self._new_row_times.popleft()
        return len(self._new_row_times) < self._cfg.max_new_per_min

    def _event(self, row: _Row, now: float) -> AlertEvent:
        rules = sorted(row.rules.values(), key=lambda f: -(f.size or 0.0))
        facts = [*rules, *row.context.values()]
        return AlertEvent(
            id=row.id,
            ts=int(now * 1000),
            symbol=row.symbol,
            market_index=row.market_index,
            rule=rules[0].kind,
            severity=row.severity(),
            direction=row.direction(),
            size=row.size(),
            price=row.price,
            facts=[f.as_dict() for f in facts],
            held=row.held,
            started_at=int(row.started_s * 1000),
            note=" · ".join(describe(f) for f in facts),
        )


@dataclass(frozen=True)
class Broad:
    """B2: the side most movers share, when enough of them share it. M4: its median per span."""

    direction: str
    move_5m: float
    spans: dict[int, float]
    same: int
    movers: int
    liquid: int
