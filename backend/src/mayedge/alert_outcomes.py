"""Follow-through of directional alerts, measured once the horizon bar has closed."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from mayedge.db import _connect, _lock
from mayedge.lighter.models import Candle

_BAR_S = 60
_DAY_MS = 86_400_000


def chained_return(returns: Mapping[int, float], start: int, end: int) -> float:
    """Compound 1m percent returns for bar opens in ``(start, end]``."""
    level = 1.0
    minute = start + _BAR_S
    while minute <= end:
        level *= 1.0 + float(returns.get(minute, 0.0)) / 100.0
        minute += _BAR_S
    return (level - 1.0) * 100.0


@dataclass(frozen=True)
class ResolvedOutcome:
    episode_id: str
    market_index: int
    symbol: str
    setup: str
    direction: str
    horizon_min: int
    opened_at: int
    raw_pct: float
    excess_pct: float
    hit: bool


class OutcomeStore(Protocol):
    def save(self, rows: Sequence[ResolvedOutcome]) -> None: ...

    def since(self, since_ms: int) -> list[ResolvedOutcome]: ...

    def purge(self, before_ms: int) -> None: ...


class MemoryOutcomeStore:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, int], ResolvedOutcome] = {}

    def save(self, rows: Sequence[ResolvedOutcome]) -> None:
        for row in rows:
            self.rows[(row.episode_id, row.horizon_min)] = row

    def since(self, since_ms: int) -> list[ResolvedOutcome]:
        return [row for row in self.rows.values() if row.opened_at >= since_ms]

    def purge(self, before_ms: int) -> None:
        self.rows = {key: row for key, row in self.rows.items() if row.opened_at >= before_ms}


def _from_sql(row: sqlite3.Row) -> ResolvedOutcome:
    return ResolvedOutcome(
        episode_id=str(row["episode_id"]),
        market_index=int(row["market_index"]),
        symbol=str(row["symbol"]),
        setup=str(row["setup"]),
        direction=str(row["direction"]),
        horizon_min=int(row["horizon_min"]),
        opened_at=int(row["opened_at"]),
        raw_pct=float(row["raw_pct"]),
        excess_pct=float(row["excess_pct"]),
        hit=bool(row["hit"]),
    )


class SqliteOutcomeStore:
    def save(self, rows: Sequence[ResolvedOutcome]) -> None:
        if not rows:
            return
        payload = [
            (
                row.episode_id,
                row.market_index,
                row.symbol,
                row.setup,
                row.direction,
                row.horizon_min,
                row.opened_at,
                row.raw_pct,
                row.excess_pct,
                1 if row.hit else 0,
            )
            for row in rows
        ]
        with _lock:
            conn = _connect()
            conn.executemany(
                """
                INSERT INTO alert_outcomes(
                    episode_id, market_index, symbol, setup, direction,
                    horizon_min, opened_at, raw_pct, excess_pct, hit
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(episode_id, horizon_min) DO UPDATE SET
                    raw_pct = excluded.raw_pct,
                    excess_pct = excluded.excess_pct,
                    hit = excluded.hit
                """,
                payload,
            )
            conn.commit()

    def since(self, since_ms: int) -> list[ResolvedOutcome]:
        with _lock:
            conn = _connect()
            found = conn.execute(
                """
                SELECT episode_id, market_index, symbol, setup, direction,
                       horizon_min, opened_at, raw_pct, excess_pct, hit
                FROM alert_outcomes
                WHERE opened_at >= ?
                """,
                (int(since_ms),),
            ).fetchall()
        return [_from_sql(row) for row in found]

    def purge(self, before_ms: int) -> None:
        with _lock:
            conn = _connect()
            conn.execute("DELETE FROM alert_outcomes WHERE opened_at < ?", (int(before_ms),))
            conn.commit()


@dataclass
class _Bucket:
    n: int = 0
    hits5: int = 0
    sum5: float = 0.0
    n15: int = 0
    hits15: int = 0
    sum15: float = 0.0


@dataclass
class _Pending:
    episode_id: str
    market_index: int
    symbol: str
    setup: str
    direction: str
    entry_bar: int
    entry_close: float
    beta: float
    opened_at: int
    done: set[int] = field(default_factory=set)


def _bar_close(bars: Sequence[Candle], bar_time: int) -> float | None:
    for bar in bars:
        if bar.time == bar_time and bar.close > 0:
            return bar.close
    return None


def _bar_closed(bars: Sequence[Candle], bar_time: int, now: float) -> bool:
    if any(bar.time > bar_time for bar in bars):
        return True
    return now >= bar_time + _BAR_S


class OutcomeBook:
    """Pending episodes in memory. Resolved rows go to the store."""

    def __init__(
        self,
        *,
        horizons: tuple[int, ...] = (5, 15),
        retention_days: int = 30,
        store: OutcomeStore | None = None,
    ) -> None:
        self._horizons = horizons
        self._retention_ms = max(1, retention_days) * _DAY_MS
        self._store = store
        self._pending: dict[str, _Pending] = {}

    def open(
        self,
        *,
        episode_id: str,
        market_index: int,
        symbol: str,
        setup: str,
        direction: str,
        entry_bar: int,
        entry_close: float,
        beta: float,
        opened_at: int,
    ) -> None:
        if direction not in ("up", "down") or entry_close <= 0 or episode_id in self._pending:
            return
        self._pending[episode_id] = _Pending(
            episode_id=episode_id,
            market_index=market_index,
            symbol=symbol,
            setup=setup,
            direction=direction,
            entry_bar=entry_bar,
            entry_close=entry_close,
            beta=beta,
            opened_at=opened_at,
        )

    def awaiting(self, market_index: int) -> bool:
        """True when this market or the broad index still has a horizon to settle."""
        for pending in self._pending.values():
            if pending.market_index == market_index or pending.market_index < 0:
                return True
        return False

    def resolve(
        self,
        market_index: int,
        bars: Sequence[Candle],
        broad_returns: Mapping[int, float],
        *,
        now: float,
    ) -> None:
        ready: list[ResolvedOutcome] = []
        for pending in self._pending.values():
            if pending.market_index != market_index:
                continue
            ready.extend(self._settle(pending, bars, broad_returns, now=now, index=False))
        for pending in list(self._pending.values()):
            if pending.market_index >= 0:
                continue
            ready.extend(self._settle(pending, (), broad_returns, now=now, index=True))
        if not ready:
            return
        store = self._db()
        store.save(ready)
        newest = max(row.opened_at for row in ready)
        store.purge(newest - self._retention_ms)
        for row in ready:
            pending = self._pending.get(row.episode_id)
            if pending is None:
                continue
            pending.done.add(row.horizon_min)
            if all(horizon in pending.done for horizon in self._horizons):
                del self._pending[row.episode_id]

    def stats(self, *, since_ms: int) -> list[dict[str, Any]]:
        episodes: dict[str, tuple[str, dict[int, ResolvedOutcome]]] = {}
        for row in self._db().since(since_ms):
            setup, horizons = episodes.get(row.episode_id, (row.setup, {}))
            horizons[row.horizon_min] = row
            episodes[row.episode_id] = (setup, horizons)
        buckets: dict[str, _Bucket] = {}
        for setup, horizons in episodes.values():
            bucket = buckets.setdefault(setup, _Bucket())
            early = horizons.get(5)
            if early is not None:
                bucket.n += 1
                bucket.hits5 += 1 if early.hit else 0
                bucket.sum5 += early.excess_pct
            late = horizons.get(15)
            if late is not None:
                bucket.n15 += 1
                bucket.hits15 += 1 if late.hit else 0
                bucket.sum15 += late.excess_pct
        rows: list[dict[str, Any]] = []
        ranked = sorted(buckets.items(), key=lambda item: (-item[1].n, item[0]))
        for setup, bucket in ranked:
            if bucket.n == 0:
                continue
            rows.append(
                {
                    "setup": setup,
                    "n": bucket.n,
                    "hit_5m": bucket.hits5 / bucket.n,
                    "hit_15m": bucket.hits15 / bucket.n15 if bucket.n15 else None,
                    "avg_ex_5m": bucket.sum5 / bucket.n,
                    "avg_ex_15m": bucket.sum15 / bucket.n15 if bucket.n15 else None,
                }
            )
        return rows

    def _db(self) -> OutcomeStore:
        if self._store is None:
            self._store = SqliteOutcomeStore()
        return self._store

    def _settle(
        self,
        pending: _Pending,
        bars: Sequence[Candle],
        broad_returns: Mapping[int, float],
        *,
        now: float,
        index: bool,
    ) -> list[ResolvedOutcome]:
        out: list[ResolvedOutcome] = []
        for horizon in self._horizons:
            if horizon in pending.done:
                continue
            horizon_bar = pending.entry_bar + horizon * _BAR_S
            if index:
                if not _index_ready(broad_returns, horizon_bar, now):
                    continue
                raw = chained_return(broad_returns, pending.entry_bar, horizon_bar)
                excess = raw
            else:
                exit_close = _bar_close(bars, horizon_bar)
                if exit_close is None or not _bar_closed(bars, horizon_bar, now):
                    continue
                raw = (exit_close - pending.entry_close) / pending.entry_close * 100.0
                excess = raw - pending.beta * chained_return(
                    broad_returns, pending.entry_bar, horizon_bar
                )
            sign = 1.0 if pending.direction == "up" else -1.0
            signed_excess = sign * excess
            out.append(
                ResolvedOutcome(
                    episode_id=pending.episode_id,
                    market_index=pending.market_index,
                    symbol=pending.symbol,
                    setup=pending.setup,
                    direction=pending.direction,
                    horizon_min=horizon,
                    opened_at=pending.opened_at,
                    raw_pct=sign * raw,
                    excess_pct=signed_excess,
                    hit=signed_excess > 0,
                )
            )
        return out


def _index_ready(broad_returns: Mapping[int, float], horizon_bar: int, now: float) -> bool:
    if horizon_bar in broad_returns or any(minute > horizon_bar for minute in broad_returns):
        return True
    return now >= horizon_bar + _BAR_S
