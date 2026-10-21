"""The record of every alert row: why it fired, what the price did after, and whether it was opened.

Left and Against start at the alert: from the price it fired at, over the bars after
the bar it fired in. The move that raised the alert is not part of either.
"""

from __future__ import annotations

import json
import sqlite3
import statistics
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol

from mayedge.db import _connect, _lock
from mayedge.lighter.models import Candle

_BAR_S = 60
_DAY_MS = 86_400_000
GROUP_BY = ("rule", "rule_severity", "rule_direction", "held", "hour", "symbol")

# knob → fact kind, stored field, which way is tighter.
# A looser knob would have raised rows that were never written, so it is not replayed.
KNOBS: dict[str, tuple[str, str, str]] = {
    "spike.price_x": ("move", "multiple", "higher"),
    "spike.min_move_pct": ("move", "abs_value", "higher"),
    "spike.volume_x": ("volume", "multiple", "higher"),
    "spike.min_volume_usd": ("volume", "value", "higher"),
    "spike.oi_x": ("oi", "multiple", "higher"),
    "spike.min_oi_usd": ("oi", "abs_usd", "higher"),
    "spike.min_oi_pct": ("oi", "abs_value", "higher"),
    "liquidations.min_usd": ("liqs", "value", "higher"),
    "liquidations.oi_bps": ("liqs", "bps", "higher"),
    "held.liq_distance_pct": ("near_liq", "value", "lower"),
    "board.median_pct": ("board", "abs_value", "higher"),
}


class UnknownKnob(ValueError):
    """The what-if was asked for a knob the record does not know how to replay."""


@dataclass(frozen=True)
class LoggedRow:
    id: str
    market_index: int
    symbol: str
    rule: str
    severity: int
    direction: str
    held: str
    fired_at: int
    price: float
    facts: str
    left_pct: float | None = None
    against_pct: float | None = None
    opened_at: int | None = None


class LogStore(Protocol):
    def upsert(self, row: LoggedRow) -> None: ...

    def measure(self, row_id: str, left_pct: float, against_pct: float) -> None: ...

    def opened(self, row_id: str, at_ms: int) -> bool: ...

    def since(self, since_ms: int) -> list[LoggedRow]: ...

    def purge(self, before_ms: int) -> None: ...


class MemoryLogStore:
    def __init__(self) -> None:
        self.rows: dict[str, LoggedRow] = {}

    def upsert(self, row: LoggedRow) -> None:
        prev = self.rows.get(row.id)
        if prev is None:
            self.rows[row.id] = row
            return
        self.rows[row.id] = replace(
            prev,
            rule=row.rule,
            severity=row.severity,
            direction=row.direction,
            held=row.held,
            facts=row.facts,
        )

    def measure(self, row_id: str, left_pct: float, against_pct: float) -> None:
        prev = self.rows.get(row_id)
        if prev is not None:
            self.rows[row_id] = replace(prev, left_pct=left_pct, against_pct=against_pct)

    def opened(self, row_id: str, at_ms: int) -> bool:
        prev = self.rows.get(row_id)
        if prev is None:
            return False
        if prev.opened_at is None:
            self.rows[row_id] = replace(prev, opened_at=at_ms)
        return True

    def since(self, since_ms: int) -> list[LoggedRow]:
        return [row for row in self.rows.values() if row.fired_at >= since_ms]

    def purge(self, before_ms: int) -> None:
        self.rows = {key: row for key, row in self.rows.items() if row.fired_at >= before_ms}


def _from_sql(row: sqlite3.Row) -> LoggedRow:
    return LoggedRow(
        id=str(row["id"]),
        market_index=int(row["market_index"]),
        symbol=str(row["symbol"]),
        rule=str(row["rule"]),
        severity=int(row["severity"]),
        direction=str(row["direction"]),
        held=str(row["held"]),
        fired_at=int(row["fired_at"]),
        price=float(row["price"]),
        facts=str(row["facts"]),
        left_pct=None if row["left_pct"] is None else float(row["left_pct"]),
        against_pct=None if row["against_pct"] is None else float(row["against_pct"]),
        opened_at=None if row["opened_at"] is None else int(row["opened_at"]),
    )


class SqliteLogStore:
    def upsert(self, row: LoggedRow) -> None:
        with _lock:
            conn = _connect()
            conn.execute(
                """
                INSERT INTO alert_rows(
                    id, market_index, symbol, rule, severity, direction, held,
                    fired_at, price, facts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    rule = excluded.rule,
                    severity = excluded.severity,
                    direction = excluded.direction,
                    held = excluded.held,
                    facts = excluded.facts
                """,
                (
                    row.id,
                    row.market_index,
                    row.symbol,
                    row.rule,
                    row.severity,
                    row.direction,
                    row.held,
                    row.fired_at,
                    row.price,
                    row.facts,
                ),
            )
            conn.commit()

    def measure(self, row_id: str, left_pct: float, against_pct: float) -> None:
        with _lock:
            conn = _connect()
            conn.execute(
                "UPDATE alert_rows SET left_pct = ?, against_pct = ? WHERE id = ?",
                (left_pct, against_pct, row_id),
            )
            conn.commit()

    def opened(self, row_id: str, at_ms: int) -> bool:
        with _lock:
            conn = _connect()
            found = conn.execute("SELECT 1 FROM alert_rows WHERE id = ?", (row_id,)).fetchone()
            if found is None:
                return False
            conn.execute(
                "UPDATE alert_rows SET opened_at = ? WHERE id = ? AND opened_at IS NULL",
                (int(at_ms), row_id),
            )
            conn.commit()
        return True

    def since(self, since_ms: int) -> list[LoggedRow]:
        with _lock:
            conn = _connect()
            found = conn.execute(
                """
                SELECT id, market_index, symbol, rule, severity, direction, held,
                       fired_at, price, facts, left_pct, against_pct, opened_at
                FROM alert_rows
                WHERE fired_at >= ?
                """,
                (int(since_ms),),
            ).fetchall()
        return [_from_sql(row) for row in found]

    def purge(self, before_ms: int) -> None:
        with _lock:
            conn = _connect()
            conn.execute("DELETE FROM alert_rows WHERE fired_at < ?", (int(before_ms),))
            conn.commit()


@dataclass
class _Pending:
    row_id: str
    market_index: int
    direction: str
    entry_bar: int
    price: float


def left_and_against(
    bars: Sequence[Candle], *, entry_bar: int, last_bar: int, price: float, direction: str
) -> tuple[float, float]:
    """Furthest the price went the row's way, and the other way, in bars after ``entry_bar``."""
    counted = [bar for bar in bars if entry_bar < bar.time <= last_bar and bar.high > 0]
    if not counted or price <= 0:
        return 0.0, 0.0
    up = max(0.0, (max(bar.high for bar in counted) - price) / price * 100.0)
    down = max(0.0, (price - min(bar.low for bar in counted)) / price * 100.0)
    return (up, down) if direction == "up" else (down, up)


class AlertLog:
    """Rows wait in memory for their bars. Everything else goes to the store."""

    def __init__(
        self,
        *,
        horizon_min: int = 15,
        retention_days: int = 30,
        log_retention_days: int | None = None,
        store: LogStore | None = None,
    ) -> None:
        self._horizon_s = max(1, horizon_min) * _BAR_S
        # alert_rows only. outcomes.retention_days is not this window.
        kept = retention_days if log_retention_days is None else log_retention_days
        self._retention_ms = max(1, kept) * _DAY_MS
        self._store = store
        self._pending: dict[str, _Pending] = {}
        self._written: set[str] = set()

    def write(self, row: Mapping[str, Any], *, entry_bar: int) -> None:
        """Record a row when it opens, and again when it changes."""
        row_id = str(row["id"])
        direction = str(row.get("direction") or "")
        market_index = int(row["market_index"])
        price = float(row.get("price") or 0.0)
        self._db().upsert(
            LoggedRow(
                id=row_id,
                market_index=market_index,
                symbol=str(row["symbol"]),
                rule=str(row["rule"]),
                severity=int(row["severity"]),
                direction=direction,
                held=str(row.get("held") or ""),
                fired_at=int(row.get("started_at") or row["ts"]),
                price=price,
                facts=json.dumps(row.get("facts") or [], separators=(",", ":")),
            )
        )
        if row_id in self._written:
            return
        self._written.add(row_id)
        # The Market row has no single price to follow.
        if market_index < 0 or price <= 0 or direction not in ("up", "down"):
            return
        self._pending[row_id] = _Pending(row_id, market_index, direction, entry_bar, price)

    def awaiting(self, market_index: int) -> bool:
        return any(p.market_index == market_index for p in self._pending.values())

    def resolve(self, market_index: int, bars: Sequence[Candle], *, now: float) -> None:
        done: list[str] = []
        for pending in self._pending.values():
            if pending.market_index != market_index:
                continue
            last_bar = pending.entry_bar + self._horizon_s
            if now < last_bar + _BAR_S and not any(bar.time > last_bar for bar in bars):
                continue
            left, against = left_and_against(
                bars,
                entry_bar=pending.entry_bar,
                last_bar=last_bar,
                price=pending.price,
                direction=pending.direction,
            )
            self._db().measure(pending.row_id, left, against)
            done.append(pending.row_id)
        if not done:
            return
        for row_id in done:
            del self._pending[row_id]
        self._db().purge(int(now * 1000) - self._retention_ms)

    def opened(self, row_id: str, *, now_ms: int) -> bool:
        return self._db().opened(row_id, now_ms)

    def stats(self, *, since_ms: int, by: str = "rule") -> list[dict[str, Any]]:
        if by not in GROUP_BY:
            raise ValueError(by)
        groups: dict[str, list[LoggedRow]] = {}
        for row in self._db().since(since_ms):
            groups.setdefault(_group_key(row, by), []).append(row)
        ranked = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
        return [_summarize(key, rows) for key, rows in ranked]

    def whatif(
        self,
        *,
        rule: str,
        knob: str,
        value: float,
        since_ms: int,
        current: float,
    ) -> dict[str, Any]:
        spec = KNOBS.get(knob)
        if spec is None:
            raise UnknownKnob(knob)
        kind, field, tighter = spec
        rows = [row for row in self._db().since(since_ms) if row.rule == rule]
        baseline = _summarize(rule, rows)
        looser = _is_looser(tighter, value, current)
        kept = (
            rows if looser else [row for row in rows if _clears(row, kind, field, value, tighter)]
        )
        return {
            "rule": rule,
            "knob": knob,
            "value": value,
            "current": current,
            "looser": looser,
            "baseline": baseline,
            "whatif": baseline if looser else _summarize(rule, kept),
        }

    def _db(self) -> LogStore:
        if self._store is None:
            self._store = SqliteLogStore()
        return self._store


def _group_key(row: LoggedRow, by: str) -> str:
    if by == "rule":
        return row.rule
    if by == "rule_severity":
        return f"{row.rule}:{row.severity}"
    if by == "rule_direction":
        return f"{row.rule}:{row.direction or 'flat'}"
    if by == "held":
        return row.held or "no"
    if by == "hour":
        return f"{time.gmtime(row.fired_at / 1000).tm_hour:02d}"
    return row.symbol


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * p
    lo = int(index)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (index - lo)


def _summarize(key: str, rows: list[LoggedRow]) -> dict[str, Any]:
    measured = [row for row in rows if row.left_pct is not None]
    lefts = [float(row.left_pct or 0.0) for row in measured]
    againsts = [float(row.against_pct or 0.0) for row in measured]
    beats = sum(1 for row in measured if (row.left_pct or 0.0) > (row.against_pct or 0.0))
    opened = sum(1 for row in rows if row.opened_at is not None)
    return {
        "rule": key,
        "key": key,
        "n": len(rows),
        "measured": len(measured),
        "left": statistics.median(lefts) if lefts else None,
        "against": statistics.median(againsts) if againsts else None,
        "left_p25": _percentile(lefts, 0.25),
        "left_p75": _percentile(lefts, 0.75),
        "against_p25": _percentile(againsts, 0.25),
        "against_p75": _percentile(againsts, 0.75),
        "left_beats": (beats / len(measured)) if measured else None,
        "opened": opened,
        "opened_rate": (opened / len(rows)) if rows else None,
    }


def _is_looser(tighter: str, value: float, current: float) -> bool:
    if tighter == "higher":
        return value < current
    return value > current


def _fact_number(row: LoggedRow, kind: str, field: str) -> float | None:
    try:
        facts = json.loads(row.facts or "[]")
    except json.JSONDecodeError:
        return None
    fact = next(
        (item for item in facts if isinstance(item, dict) and item.get("kind") == kind), None
    )
    if fact is None:
        return None
    if field == "multiple":
        raw = fact.get("multiple")
    elif field == "bps":
        raw = fact.get("bps")
    elif field == "abs_usd":
        raw = fact.get("usd")
        return None if raw is None else abs(float(raw))
    elif field == "abs_value":
        raw = fact.get("value")
        return None if raw is None else abs(float(raw))
    else:
        raw = fact.get("value")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _clears(row: LoggedRow, kind: str, field: str, value: float, tighter: str) -> bool:
    number = _fact_number(row, kind, field)
    if number is None:
        return False
    if tighter == "higher":
        return number >= value
    return number <= value
