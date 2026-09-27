"""Open-interest samples. A level, not a flow: minutes for 30 days, then a daily high/low/close."""

from __future__ import annotations

import logging
import math
import time
from typing import Any

from mayedge.db import _connect, _lock

logger = logging.getLogger(__name__)

OI_MINUTE_S = 60
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
    fold_open_interest_if_due()
    return len(payload)


def list_open_interest(
    market_index: int,
    *,
    resolution: str,
    count: int,
) -> list[dict[str, Any]]:
    """Last `count` bucket closes for one market. Time is unix seconds at the bucket open.

    Gaps are omitted. A 1d bucket inside the detail horizon uses the last minute;
    an older day uses that day's close.
    """
    step = OI_RESOLUTIONS.get(resolution)
    if step is None:
        raise ValueError("resolution must be 1m, 5m, 15m, 1h, 4h, or 1d")
    n = max(1, min(int(count), 3600))
    idx = int(market_index)
    with _lock:
        conn = _connect()
        day_rows: list[Any] = []
        if resolution == "1d":
            day_rows = conn.execute(
                """
                SELECT day_index * ? AS time, oi_close AS open_interest
                FROM oi_days
                WHERE market_index = ?
                """,
                (OI_DAY_S, idx),
            ).fetchall()
        sample_rows = conn.execute(
            """
            WITH ranked AS (
                SELECT
                    (minute_index * ?) / ? AS bucket,
                    oi_usd,
                    ROW_NUMBER() OVER (
                        PARTITION BY (minute_index * ?) / ?
                        ORDER BY minute_index DESC
                    ) AS rn
                FROM oi_samples
                WHERE market_index = ?
            )
            SELECT bucket * ? AS time, oi_usd AS open_interest
            FROM ranked
            WHERE rn = 1
            ORDER BY bucket DESC
            LIMIT ?
            """,
            (OI_MINUTE_S, step, OI_MINUTE_S, step, idx, step, n),
        ).fetchall()
    by_time: dict[int, float] = {}
    for row in day_rows:
        by_time[int(row["time"])] = float(row["open_interest"])
    for row in sample_rows:
        by_time[int(row["time"])] = float(row["open_interest"])
    times = sorted(by_time)
    if len(times) > n:
        times = times[-n:]
    return [{"time": t, "open_interest": by_time[t]} for t in times]


def fold_open_interest(*, now_ms: int) -> int:
    """Fold UTC days fully older than 30 days into one high/low/close. Returns minutes removed."""
    fold_before_day = (int(now_ms) - OI_DETAIL_MS) // OI_DAY_MS
    with _lock:
        conn = _connect()
        try:
            removed = _fold_locked(conn, fold_before_day)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return removed


def _fold_locked(conn: Any, fold_before_day: int) -> int:
    params = (OI_MINUTE_S, OI_DAY_S, OI_MINUTE_S, OI_DAY_S, int(fold_before_day))
    conn.execute(
        """
        WITH foldable AS (
            SELECT
                market_index,
                symbol,
                minute_index,
                oi_usd,
                (minute_index * ?) / ? AS day_index
            FROM oi_samples
            WHERE (minute_index * ?) / ? < ?
        ),
        ranked AS (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY day_index, market_index
                    ORDER BY minute_index DESC
                ) AS rn
            FROM foldable
        )
        INSERT INTO oi_days (day_index, market_index, symbol, oi_high, oi_low, oi_close)
        SELECT
            day_index,
            market_index,
            MAX(CASE WHEN rn = 1 THEN symbol END),
            MAX(oi_usd),
            MIN(oi_usd),
            MAX(CASE WHEN rn = 1 THEN oi_usd END)
        FROM ranked
        GROUP BY day_index, market_index
        ON CONFLICT(day_index, market_index) DO UPDATE SET
            symbol = excluded.symbol,
            oi_high = CASE
                WHEN excluded.oi_high > oi_days.oi_high THEN excluded.oi_high
                ELSE oi_days.oi_high
            END,
            oi_low = CASE
                WHEN excluded.oi_low < oi_days.oi_low THEN excluded.oi_low
                ELSE oi_days.oi_low
            END,
            oi_close = excluded.oi_close
        """,
        params,
    )
    conn.execute(
        """
        DELETE FROM oi_samples
        WHERE (minute_index * ?) / ? < ?
        """,
        (OI_MINUTE_S, OI_DAY_S, int(fold_before_day)),
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
