"""Open-interest samples. A level, not a flow: minutes for 30 days, then an hourly high/low/close."""

from __future__ import annotations

import logging
import math
import time
from typing import Any

from mayedge.db import _connect, _lock, reading

logger = logging.getLogger(__name__)

OI_MINUTE_S = 60
OI_HOUR_S = 3600
OI_HOUR_MS = OI_HOUR_S * 1000
OI_DAY_S = 86_400
OI_DAY_MS = OI_DAY_S * 1000
OI_DETAIL_MS = 30 * OI_DAY_MS
OI_RESOLUTIONS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


def open_interest_sample_rows(markets: Any) -> list[dict[str, Any]]:
    """Perp prints only. Spot and a missing or non-positive level are skipped."""
    rows: list[dict[str, Any]] = []
    for meta in markets:
        if not getattr(meta, "is_perp", False):
            continue
        oi = getattr(meta, "open_interest", None)
        if oi is None:
            continue
        try:
            value = float(oi)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value) or value <= 0:
            continue
        rows.append(
            {
                "market_index": int(meta.market_index),
                "symbol": str(meta.symbol),
                "oi_usd": value,
            }
        )
    return rows


def flush_open_interest(rows: list[dict[str, Any]], *, minute_index: int) -> int:
    """Upsert each perp's open interest into one UTC minute. Returns rows written."""
    minute = int(minute_index)
    if minute < 0 or not rows:
        return 0
    payload: list[tuple[int, int, str, float]] = []
    for row in rows:
        try:
            oi = float(row["oi_usd"])
        except (KeyError, TypeError, ValueError):
            continue
        if not math.isfinite(oi) or oi <= 0:
            continue
        payload.append((int(row["market_index"]), minute, str(row.get("symbol") or ""), oi))
    if not payload:
        return 0
    with _lock:
        conn = _connect()
        conn.executemany(
            """
            INSERT INTO oi_samples(market_index, minute_index, symbol, oi_usd)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(market_index, minute_index) DO UPDATE SET
                symbol = excluded.symbol,
                oi_usd = excluded.oi_usd
            """,
            payload,
        )
        conn.commit()
    return len(payload)


def recent_open_interest(since_minute: int) -> dict[int, list[tuple[int, float]]]:
    """Each perp's stored minutes from ``since_minute`` on, oldest first."""
    with _lock:
        conn = _connect()
        found = conn.execute(
            """
            SELECT market_index, minute_index, oi_usd
            FROM oi_samples
            WHERE minute_index >= ?
            ORDER BY minute_index
            """,
            (int(since_minute),),
        ).fetchall()
    out: dict[int, list[tuple[int, float]]] = {}
    for row in found:
        out.setdefault(int(row["market_index"]), []).append(
            (int(row["minute_index"]), float(row["oi_usd"]))
        )
    return out


def list_open_interest(
    market_index: int,
    *,
    resolution: str,
    count: int,
) -> list[dict[str, Any]]:
    """Last `count` bucket closes for one market. Time is unix seconds at the bucket open.

    Gaps are omitted. Minutes cover the last 30 days. Older history is hourly, so
    1h, 4h and 1d buckets reach back to the first sample; 1m-15m stop at 30 days.
    """
    step = OI_RESOLUTIONS.get(resolution)
    if step is None:
        raise ValueError("resolution must be 1m, 5m, 15m, 1h, 4h, or 1d")
    n = max(1, min(int(count), 3600))
    idx = int(market_index)
    with reading() as conn:
        hour_rows: list[Any] = []
        if step >= OI_HOUR_S:
            hour_rows = conn.execute(
                _LAST_IN_BUCKET.format(table="oi_hours", col="hour_index", value="oi_close"),
                (OI_HOUR_S, step, OI_HOUR_S, step, idx, step, n),
            ).fetchall()
        sample_rows = conn.execute(
            _LAST_IN_BUCKET.format(table="oi_samples", col="minute_index", value="oi_usd"),
            (OI_MINUTE_S, step, OI_MINUTE_S, step, idx, step, n),
        ).fetchall()
    by_time: dict[int, float] = {}
    for row in hour_rows:
        by_time[int(row["time"])] = float(row["open_interest"])
    # Minutes are later than any folded hour in the same bucket, so they hold its close.
    for row in sample_rows:
        by_time[int(row["time"])] = float(row["open_interest"])
    times = sorted(by_time)
    if len(times) > n:
        times = times[-n:]
    return [{"time": t, "open_interest": by_time[t]} for t in times]


_LAST_IN_BUCKET = """
    WITH ranked AS (
        SELECT
            ({col} * ?) / ? AS bucket,
            {value} AS value,
            ROW_NUMBER() OVER (
                PARTITION BY ({col} * ?) / ?
                ORDER BY {col} DESC
            ) AS rn
        FROM {table}
        WHERE market_index = ?
    )
    SELECT bucket * ? AS time, value AS open_interest
    FROM ranked
    WHERE rn = 1
    ORDER BY bucket DESC
    LIMIT ?
"""


_MINUTES_PER_HOUR = OI_HOUR_S // OI_MINUTE_S
_HOURS_PER_CHUNK = 24

# Hour bucketing stays in the SELECT. The filter is a bare minute bound so
# idx_oi_samples_minute can search it. One statement covers one day of hours.
_FOLD_INSERT = """
    WITH foldable AS (
        SELECT
            market_index,
            symbol,
            minute_index,
            oi_usd,
            (minute_index * ?) / ? AS hour_index
        FROM oi_samples
        WHERE minute_index >= ? AND minute_index < ?
    ),
    ranked AS (
        SELECT
            *,
            ROW_NUMBER() OVER (
                PARTITION BY hour_index, market_index
                ORDER BY minute_index DESC
            ) AS rn
        FROM foldable
    )
    INSERT INTO oi_hours (hour_index, market_index, symbol, oi_high, oi_low, oi_close)
    SELECT
        hour_index,
        market_index,
        MAX(CASE WHEN rn = 1 THEN symbol END),
        MAX(oi_usd),
        MIN(oi_usd),
        MAX(CASE WHEN rn = 1 THEN oi_usd END)
    FROM ranked
    GROUP BY hour_index, market_index
    ON CONFLICT(hour_index, market_index) DO UPDATE SET
        symbol = excluded.symbol,
        oi_high = CASE
            WHEN excluded.oi_high > oi_hours.oi_high THEN excluded.oi_high
            ELSE oi_hours.oi_high
        END,
        oi_low = CASE
            WHEN excluded.oi_low < oi_hours.oi_low THEN excluded.oi_low
            ELSE oi_hours.oi_low
        END,
        oi_close = excluded.oi_close
"""


def fold_open_interest(*, now_ms: int) -> int:
    """Fold UTC hours fully older than 30 days into one high/low/close. Returns minutes removed."""
    fold_before_hour = (int(now_ms) - OI_DETAIL_MS) // OI_HOUR_MS
    cutoff = int(fold_before_hour) * _MINUTES_PER_HOUR
    removed = 0
    while True:
        with _lock:
            conn = _connect()
            try:
                n = _fold_locked(conn, cutoff)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        if n == 0:
            return removed
        removed += n


def _fold_locked(conn: Any, cutoff: int) -> int:
    """Fold at most one day of hours with minute_index < cutoff. Returns minutes removed."""
    row = conn.execute(
        "SELECT MIN(minute_index) AS minute FROM oi_samples WHERE minute_index < ?",
        (int(cutoff),),
    ).fetchone()
    if row is None or row["minute"] is None:
        return 0
    start = (int(row["minute"]) // _MINUTES_PER_HOUR) * _MINUTES_PER_HOUR
    end = min(int(cutoff), start + _HOURS_PER_CHUNK * _MINUTES_PER_HOUR)
    conn.execute(_FOLD_INSERT, (OI_MINUTE_S, OI_HOUR_S, start, end))
    conn.execute(
        "DELETE FROM oi_samples WHERE minute_index >= ? AND minute_index < ?",
        (start, end),
    )
    removed = conn.execute("SELECT changes()").fetchone()
    return int(removed[0] if removed is not None else 0)


def fold_open_interest_if_due() -> None:
    import mayedge.db as db

    now = time.time()
    if now - db._last_oi_fold_at < 3600:
        return
    try:
        fold_open_interest(now_ms=int(now * 1000))
    except Exception:
        logger.exception("failed to fold open interest days")
        return
    db._last_oi_fold_at = now
