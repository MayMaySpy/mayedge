"""Funding: the venue's estimate each UTC minute, and the rate it settled each hour.

Minute samples are kept 30 days; they tell the alert rules what is normal after a
restart and show the hour that has not settled yet. Funding prints are kept for the
life of the desk.
"""

from __future__ import annotations

import math
import time
from typing import Any

from mayedge.db import _connect, _lock, _set_meta, reading

FUNDING_HOUR_S = 3600
FUNDING_DAY_S = 86_400
HOURS_PER_DAY = 24
FUNDING_MINUTE_S = 60
FUNDING_RESOLUTIONS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


def funding_sample_rows(markets: Any) -> list[dict[str, Any]]:
    """Perp prints only. A missing rate is skipped; a rate of zero is a rate."""
    rows: list[dict[str, Any]] = []
    for meta in markets:
        if not getattr(meta, "is_perp", False):
            continue
        rate = getattr(meta, "funding_rate", None)
        if rate is None:
            continue
        try:
            value = float(rate)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value):
            continue
        rows.append({"market_index": int(meta.market_index), "funding": value})
    return rows


def funding_print_rows(markets: Any) -> list[dict[str, Any]]:
    """Each perp's last settled print, filed under the hour it paid for.

    The venue stamps a print with the time it settled, the end of its hour.
    """
    rows: list[dict[str, Any]] = []
    for meta in markets:
        if not getattr(meta, "is_perp", False):
            continue
        rate = getattr(meta, "settled_funding_rate", None)
        stamp = getattr(meta, "funding_timestamp", None)
        if rate is None or stamp is None:
            continue
        try:
            value = float(rate)
            settled_s = int(stamp) // 1000
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value) or settled_s <= 0:
            continue
        rows.append(
            {
                "market_index": int(meta.market_index),
                "hour_index": settled_s // FUNDING_HOUR_S - 1,
                "rate": value,
            }
        )
    return rows


def flush_funding_prints(rows: list[dict[str, Any]]) -> int:
    """Upsert each perp's print for its hour. Prints are never dropped."""
    if not rows:
        return 0
    payload = [
        (int(row["market_index"]), int(row["hour_index"]), float(row["rate"])) for row in rows
    ]
    with _lock:
        conn = _connect()
        conn.executemany(
            """
            INSERT INTO funding_prints(market_index, hour_index, rate)
            VALUES (?, ?, ?)
            ON CONFLICT(market_index, hour_index) DO UPDATE SET rate = excluded.rate
            """,
            payload,
        )
        conn.commit()
    return len(payload)


def insert_missing_funding_prints(rows: list[dict[str, Any]]) -> int:
    """Backfilled prints. A print the desk recorded live is never replaced."""
    if not rows:
        return 0
    payload = [
        (int(row["market_index"]), int(row["hour_index"]), float(row["rate"])) for row in rows
    ]
    with _lock:
        conn = _connect()
        before = conn.total_changes
        conn.executemany(
            "INSERT OR IGNORE INTO funding_prints(market_index, hour_index, rate) VALUES (?, ?, ?)",
            payload,
        )
        written = conn.total_changes - before
        conn.commit()
    return written


def recent_funding_prints(since_hour: int) -> dict[int, dict[int, float]]:
    """Each perp's prints from ``since_hour`` on, by hour."""
    with _lock:
        conn = _connect()
        found = conn.execute(
            "SELECT market_index, hour_index, rate FROM funding_prints WHERE hour_index >= ?",
            (int(since_hour),),
        ).fetchall()
    out: dict[int, dict[int, float]] = {}
    for row in found:
        out.setdefault(int(row["market_index"]), {})[int(row["hour_index"])] = float(row["rate"])
    return out


def funding_prints_for(market_index: int, since_hour: int) -> dict[int, float]:
    """One perp's prints from ``since_hour`` on, by hour."""
    with _lock:
        conn = _connect()
        found = conn.execute(
            "SELECT hour_index, rate FROM funding_prints WHERE market_index = ? AND hour_index >= ?",
            (int(market_index), int(since_hour)),
        ).fetchall()
    return {int(row["hour_index"]): float(row["rate"]) for row in found}


def insert_funding_days(rows: list[dict[str, Any]]) -> int:
    """Funding days from the venue: the mean 1h rate of one UTC day, in percent."""
    if not rows:
        return 0
    payload = [
        (int(row["market_index"]), int(row["day_index"]), float(row["rate"])) for row in rows
    ]
    with _lock:
        conn = _connect()
        conn.executemany(
            """
            INSERT INTO funding_days(market_index, day_index, rate) VALUES (?, ?, ?)
            ON CONFLICT(market_index, day_index) DO UPDATE SET rate = excluded.rate
            """,
            payload,
        )
        conn.commit()
    return len(payload)


def _funding_days_for(conn: Any, market_index: int, since_day: int) -> dict[int, float]:
    found = conn.execute(
        "SELECT day_index, rate FROM funding_days WHERE market_index = ? AND day_index >= ?",
        (int(market_index), int(since_day)),
    ).fetchall()
    return {int(row["day_index"]): float(row["rate"]) for row in found}


def _days_key(market_index: int) -> str:
    return f"funding_days_backfill:{int(market_index)}"


def funding_days_backfill_done(market_index: int) -> bool:
    with _lock:
        conn = _connect()
        row = conn.execute(
            "SELECT 1 FROM meta WHERE key = ?", (_days_key(market_index),)
        ).fetchone()
    return row is not None


def mark_funding_days_backfill_done(market_index: int, oldest_day: int | None) -> None:
    with _lock:
        conn = _connect()
        _set_meta(conn, _days_key(market_index), str(oldest_day if oldest_day is not None else ""))
        conn.commit()


def _backfill_key(market_index: int) -> str:
    return f"funding_backfill:{int(market_index)}"


def funding_backfill_done(market_index: int) -> bool:
    with _lock:
        conn = _connect()
        row = conn.execute(
            "SELECT 1 FROM meta WHERE key = ?", (_backfill_key(market_index),)
        ).fetchone()
    return row is not None


def mark_funding_backfill_done(market_index: int, oldest_hour: int | None) -> None:
    with _lock:
        conn = _connect()
        _set_meta(
            conn, _backfill_key(market_index), str(oldest_hour if oldest_hour is not None else "")
        )
        conn.commit()


FUNDING_AVERAGE_WINDOWS: tuple[tuple[str, int], ...] = (("7d", 7), ("30d", 30), ("1y", 365))


def funding_averages(market_index: int, *, now: float | None = None) -> dict[str, Any]:
    """Mean 1h rate over the last 7 days, 30 days and year, from settled funding only.

    A day without all 24 prints uses its Funding day when the venue gave one, and
    counts as 24 hours. Each window says how many hours it holds, so a short history
    is not read as a year.
    """
    clock = time.time() if now is None else float(now)
    this_hour = int(clock) // FUNDING_HOUR_S
    longest = max(days for _label, days in FUNDING_AVERAGE_WINDOWS)
    since_hour = this_hour - longest * HOURS_PER_DAY
    idx = int(market_index)
    with reading() as conn:
        found = conn.execute(
            """
            SELECT hour_index, rate FROM funding_prints
            WHERE market_index = ? AND hour_index >= ? AND hour_index < ?
            """,
            (idx, since_hour, this_hour),
        ).fetchall()
        day_rows = _funding_days_for(conn, idx, since_hour // HOURS_PER_DAY)
    by_day: dict[int, list[tuple[int, float]]] = {}
    for row in found:
        hour = int(row["hour_index"])
        by_day.setdefault(hour // HOURS_PER_DAY, []).append((hour, float(row["rate"])))
    this_day = this_hour // HOURS_PER_DAY
    # Days the venue's daily row stands in for: complete, and short of 24 prints.
    from_days = {
        day: rate
        for day, rate in day_rows.items()
        if day < this_day and len(by_day.get(day, ())) < HOURS_PER_DAY
    }
    windows: list[dict[str, Any]] = []
    for label, days in FUNDING_AVERAGE_WINDOWS:
        start = this_hour - days * HOURS_PER_DAY
        total = 0.0
        hours = 0
        venue_days = 0
        for day, prints in by_day.items():
            if day in from_days and day * HOURS_PER_DAY >= start:
                continue
            for hour, rate in prints:
                if hour >= start:
                    total += rate
                    hours += 1
        for day, rate in from_days.items():
            if day * HOURS_PER_DAY >= start:
                total += rate * HOURS_PER_DAY
                hours += HOURS_PER_DAY
                venue_days += 1
        windows.append(
            {
                "label": label,
                "days": days,
                "hours": hours,
                "venue_days": venue_days,
                "rate": total / hours if hours else None,
            }
        )
    firsts = [hour for prints in by_day.values() for hour, _rate in prints]
    firsts += [day * HOURS_PER_DAY for day in from_days]
    first = min(firsts, default=None)
    return {
        "windows": windows,
        "first_time": first * FUNDING_HOUR_S if first is not None else None,
    }


def flush_funding(rows: list[dict[str, Any]], *, minute_index: int, keep_minutes: int) -> int:
    """Upsert each perp's funding rate into one UTC minute and drop minutes past retention."""
    minute = int(minute_index)
    if minute < 0 or not rows:
        return 0
    payload = [(int(row["market_index"]), minute, float(row["funding"])) for row in rows]
    with _lock:
        conn = _connect()
        conn.executemany(
            """
            INSERT INTO funding_samples(market_index, minute_index, funding)
            VALUES (?, ?, ?)
            ON CONFLICT(market_index, minute_index) DO UPDATE SET funding = excluded.funding
            """,
            payload,
        )
        conn.execute(
            "DELETE FROM funding_samples WHERE minute_index < ?", (minute - int(keep_minutes),)
        )
        conn.commit()
    return len(payload)


def recent_funding(since_minute: int) -> dict[int, list[tuple[int, float]]]:
    """Each perp's stored minutes from ``since_minute`` on, oldest first."""
    with _lock:
        conn = _connect()
        found = conn.execute(
            """
            SELECT market_index, minute_index, funding
            FROM funding_samples
            WHERE minute_index >= ?
            ORDER BY minute_index
            """,
            (int(since_minute),),
        ).fetchall()
    out: dict[int, list[tuple[int, float]]] = {}
    for row in found:
        out.setdefault(int(row["market_index"]), []).append(
            (int(row["minute_index"]), float(row["funding"]))
        )
    return out


def list_funding(
    market_index: int,
    *,
    resolution: str,
    count: int,
    now: float | None = None,
) -> list[dict[str, Any]]:
    """Up to `count` buckets of the 1h rate, in percent. Time is unix seconds at the bucket open.

    A bucket with prints is their mean and is settled. A 1d bucket short of 24 prints
    uses the Funding day when there is one. A bucket with neither falls back to the
    last minute estimate in it and is not settled. Empty buckets are omitted.
    """
    step = FUNDING_RESOLUTIONS.get(resolution)
    if step is None:
        raise ValueError("resolution must be 1m, 5m, 15m, 1h, 4h, or 1d")
    n = max(1, min(int(count), 3600))
    clock = time.time() if now is None else float(now)
    first_bucket = (int(clock) // step - n + 1) * step
    idx = int(market_index)
    with reading() as conn:
        prints = conn.execute(
            """
            SELECT hour_index, rate FROM funding_prints
            WHERE market_index = ? AND hour_index >= ?
            ORDER BY hour_index
            """,
            (idx, first_bucket // FUNDING_HOUR_S),
        ).fetchall()
        day_rows = (
            _funding_days_for(conn, idx, first_bucket // FUNDING_DAY_S)
            if step == FUNDING_DAY_S
            else {}
        )
        samples = conn.execute(
            """
            SELECT minute_index, funding FROM funding_samples
            WHERE market_index = ? AND minute_index >= ?
            ORDER BY minute_index
            """,
            (idx, first_bucket // FUNDING_MINUTE_S),
        ).fetchall()
    settled: dict[int, list[float]] = {}
    for row in prints:
        hour_s = int(row["hour_index"]) * FUNDING_HOUR_S
        rate = float(row["rate"])
        if step >= FUNDING_HOUR_S:
            settled.setdefault(hour_s // step * step, []).append(rate)
        else:
            for t in range(hour_s, hour_s + FUNDING_HOUR_S, step):
                settled.setdefault(t, []).append(rate)
    # A day short of 24 prints takes the venue's Funding day; the day in progress has none.
    for day, rate in day_rows.items():
        t = day * FUNDING_DAY_S
        if t + FUNDING_DAY_S <= clock and len(settled.get(t, ())) < HOURS_PER_DAY:
            settled[t] = [rate]
    estimate: dict[int, float] = {}
    for row in samples:
        t = int(row["minute_index"]) * FUNDING_MINUTE_S // step * step
        estimate[t] = float(row["funding"])
    out: list[dict[str, Any]] = []
    for t in sorted(set(settled) | set(estimate)):
        if t < first_bucket:
            continue
        rates = settled.get(t)
        if rates:
            out.append({"time": t, "rate": sum(rates) / len(rates), "settled": True})
        else:
            out.append({"time": t, "rate": estimate[t], "settled": False})
    return out[-n:]
