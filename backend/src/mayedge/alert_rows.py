"""What an alert is: the snapshot it reads, the facts it states, and the rows the panel shows."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from mayedge.alert_settings import AlertSettings

NOTABLE = 2
URGENT = 3
SPIKE_KINDS = frozenset({"move", "volume", "oi"})
# R4: states that go on firing once they start.
STATE_KINDS = frozenset({"liqs", "board", "near_liq"})
# R4: a state that keeps firing raises another row at half again its largest size.
_ESCALATE = 1.5
# How many times the hour's biggest a minute can be said to be.
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


def _hour(fact: Fact) -> str:
    multiple = fact.detail.get("multiple")
    return "" if multiple is None else f" · {multiple:.1f}× hour max"


def describe(fact: Fact) -> str:
    """The fact in desk shorthand. No label says what it means."""
    v = fact.value
    if fact.kind == "move":
        text = f"{v:+.2f}% 1m"
        if fact.size is not None:
            text += _hour(fact)
        excess = fact.detail.get("excess")
        if excess is not None:
            text += f" · {excess:+.2f}% past the board"
        return text
    if fact.kind == "volume":
        return f"Vol {_usd(v)} 1m{_hour(fact)}"
    if fact.kind == "oi":
        return f"OI {v:+.2f}% 1m{_hour(fact)}"
    if fact.kind == "liqs":
        side = "longs" if fact.direction == "down" else "shorts"
        return f"Liqs {_usd(v)} {side} · {fact.detail.get('bps', 0.0):.0f} bps of OI"
    if fact.kind == "board":
        return f"Board {v:+.2f}% · {fact.window} {fact.direction}"
    if fact.kind == "near_liq":
        return f"{v:.1f}% from liquidation"
    if fact.kind == "day_high":
        return "day high"
    if fact.kind == "day_low":
        return "day low"
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
        """R3."""
        spikes = sum(1 for kind in self.rules if kind in SPIKE_KINDS)
        if spikes >= 2 or self.held or any(kind in STATE_KINDS for kind in self.rules):
            return URGENT
        return NOTABLE

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
        """K7 for a spike: always. R4 for a state: when it starts, and when it grows by half."""
        if fact.kind not in STATE_KINDS:
            return True
        key = (market_index, fact.kind)
        size = fact.size or 0.0
        standing = self._standing.get(key)
        if standing is None or now - standing[1] >= self._cfg.quiet_s:
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
    """B2: the side most movers share, when enough of them share it."""

    direction: str
    move_5m: float
    move_1m: float
    same: int
    movers: int
    liquid: int
