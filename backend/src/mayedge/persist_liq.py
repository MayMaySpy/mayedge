"""Liquidation SQLite persistence."""

from __future__ import annotations

import logging
import time
from typing import Any

from mayedge.db import _connect, _lock

logger = logging.getLogger(__name__)

LIQ_SUMMARY_HOURS = (1, 4, 24, 168, 720)
LIQ_DAY_MS = 86_400_000
LIQ_DETAIL_MS = 30 * LIQ_DAY_MS

_FOLDABLE_CTE = """
WITH fills AS (
    SELECT
        trade_id,
        market_index,
        symbol,
        side,
        ts,
        CAST(COALESCE(NULLIF(usd_amount, ''), '0') AS REAL) AS usd,
        COALESCE(NULLIF(group_id, ''), 't' || trade_id) AS gid
    FROM liquidations
),
starts AS (
    SELECT market_index, gid, MIN(ts) AS start_ts
    FROM fills
    GROUP BY market_index, gid
    HAVING MIN(ts) / ? < ?
),
foldable AS (
    SELECT
        f.trade_id AS trade_id,
        f.market_index AS market_index,
        f.symbol AS symbol,
        f.side AS side,
        f.usd AS usd,
        f.gid AS gid,
        s.start_ts / ? AS day_index
    FROM fills f
    JOIN starts s ON s.market_index = f.market_index AND s.gid = f.gid
)
"""


def liquidation_summary_since_ms(hours: int, now_ms: int | None = None) -> int:
    if hours not in LIQ_SUMMARY_HOURS:
        raise ValueError("hours must be 1, 4, 24, 168, or 720")
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    return now - hours * 3_600_000


def insert_liquidations(rows: list[dict[str, Any]]) -> int:
    """Insert liquidation events; ignore duplicate trade_ids. Returns inserted count."""
    if not rows:
        return 0
    inserted = 0
    with _lock:
        conn = _connect()
        for r in rows:
            tid = int(r["trade_id"])
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO liquidations(
                    trade_id, market_index, symbol, kind, side, price, size, usd_amount, ts, group_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tid,
                    int(r["market_index"]),
                    str(r.get("symbol") or ""),
                    str(r.get("kind") or "liquidation"),
                    r.get("side"),
                    str(r.get("price") or "0"),
                    str(r.get("size") or "0"),
                    r.get("usd_amount"),
                    int(r.get("ts") or 0),
                    str(r.get("group_id") or "") or None,
                ),
            )
            inserted += cur.rowcount
        conn.commit()
    fold_liquidations_if_due()
    return inserted


def list_liquidations(
    *,
    limit: int = 200,
    min_usd: float | None = None,
    market_index: int | None = None,
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 1000))
    clauses: list[str] = []
    params: list[Any] = []
    if market_index is not None:
        clauses.append("market_index = ?")
        params.append(int(market_index))
    if min_usd is not None and min_usd > 0:
        clauses.append("CAST(COALESCE(NULLIF(usd_amount, ''), '0') AS REAL) >= ?")
        params.append(float(min_usd))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with _lock:
        conn = _connect()
        rows = conn.execute(
            f"""
            SELECT trade_id, market_index, symbol, kind, side, price, size, usd_amount, ts, group_id
            FROM liquidations
            {where}
            ORDER BY ts DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [
        {
            "trade_id": str(r["trade_id"]),
            "market_index": r["market_index"],
            "symbol": r["symbol"],
            "kind": r["kind"],
            "side": r["side"],
            "price": r["price"],
            "size": r["size"],
            "usd_amount": r["usd_amount"],
            "timestamp": r["ts"],
            "group_id": r["group_id"] or "",
        }
        for r in rows
    ]


def _first_day_index(since_ms: int) -> int:
    """First UTC day whose start is still inside the window."""
    cutoff = int(since_ms)
    if cutoff <= 0:
        return 0
    return (cutoff + LIQ_DAY_MS - 1) // LIQ_DAY_MS


def summarize_liquidations(*, since_ms: int) -> list[dict[str, Any]]:
    """Aggregate the window: raw fills, plus Liquidation days fully inside it.

    long = sell, short = buy. largest_usd is one liquidation (one taker order).
    A 30-day window never reaches a folded day; those days are fully older than the detail horizon.
    """
    cutoff = int(since_ms)
    first_day = _first_day_index(cutoff)
    with _lock:
        conn = _connect()
        rows = conn.execute(
            """
            WITH fills AS (
                SELECT
                    symbol,
                    market_index,
                    side,
                    CAST(COALESCE(NULLIF(usd_amount, ''), '0') AS REAL) AS usd,
                    COALESCE(NULLIF(group_id, ''), 't' || trade_id) AS gid
                FROM liquidations
                WHERE ts >= ?
            ),
            raw AS (
                SELECT
                    f.symbol AS symbol,
                    f.market_index AS market_index,
                    SUM(CASE WHEN f.side = 'sell' THEN f.usd ELSE 0 END) AS long_usd,
                    SUM(CASE WHEN f.side = 'buy' THEN f.usd ELSE 0 END) AS short_usd,
                    SUM(f.usd) AS total_usd,
                    COUNT(*) AS fill_count,
                    MAX(g.group_usd) AS largest_usd
                FROM fills f
                JOIN (
                    SELECT market_index, gid, SUM(usd) AS group_usd
                    FROM fills
                    GROUP BY market_index, gid
                ) g ON g.market_index = f.market_index AND g.gid = f.gid
                GROUP BY f.symbol, f.market_index
            ),
            days AS (
                SELECT
                    symbol,
                    market_index,
                    long_usd,
                    short_usd,
                    total_usd,
                    fill_count,
                    largest_usd
                FROM liquidation_days
                WHERE day_index >= ?
            ),
            combined AS (
                SELECT * FROM raw
                UNION ALL
                SELECT * FROM days
            )
            SELECT
                MAX(symbol) AS symbol,
                market_index,
                SUM(long_usd) AS long_usd,
                SUM(short_usd) AS short_usd,
                SUM(total_usd) AS total_usd,
                SUM(fill_count) AS fill_count,
                MAX(largest_usd) AS largest_usd
            FROM combined
            GROUP BY market_index
            HAVING total_usd > 0
            ORDER BY total_usd DESC, symbol ASC
            """,
            (cutoff, first_day),
        ).fetchall()
    return [
        {
            "symbol": r["symbol"],
            "market_index": r["market_index"],
            "long_usd": float(r["long_usd"] or 0),
            "short_usd": float(r["short_usd"] or 0),
            "total_usd": float(r["total_usd"] or 0),
            "fill_count": int(r["fill_count"] or 0),
            "largest_usd": float(r["largest_usd"] or 0),
        }
        for r in rows
    ]


def fold_liquidations(*, now_ms: int) -> int:
    """Fold UTC days fully older than 30 days into one row per Market. Returns fills removed."""
    fold_before_day = (int(now_ms) - LIQ_DETAIL_MS) // LIQ_DAY_MS
    params = (LIQ_DAY_MS, fold_before_day, LIQ_DAY_MS)
    with _lock:
        conn = _connect()
        try:
            removed = _fold_locked(conn, params)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return removed


def _fold_locked(conn: Any, params: tuple[int, int, int]) -> int:
    conn.execute(
        _FOLDABLE_CTE
        + """
        INSERT INTO liquidation_days (
            day_index, market_index, symbol,
            long_usd, short_usd, total_usd, fill_count, largest_usd
        )
        SELECT
            f.day_index,
            f.market_index,
            MAX(f.symbol),
            SUM(CASE WHEN f.side = 'sell' THEN f.usd ELSE 0 END),
            SUM(CASE WHEN f.side = 'buy' THEN f.usd ELSE 0 END),
            SUM(f.usd),
            COUNT(*),
            MAX(g.group_usd)
        FROM foldable f
        JOIN (
            SELECT day_index, market_index, gid, SUM(usd) AS group_usd
            FROM foldable
            GROUP BY day_index, market_index, gid
        ) g
            ON g.day_index = f.day_index
            AND g.market_index = f.market_index
            AND g.gid = f.gid
        GROUP BY f.day_index, f.market_index
        HAVING SUM(f.usd) > 0
        ON CONFLICT(day_index, market_index) DO UPDATE SET
            symbol = excluded.symbol,
            long_usd = liquidation_days.long_usd + excluded.long_usd,
            short_usd = liquidation_days.short_usd + excluded.short_usd,
            total_usd = liquidation_days.total_usd + excluded.total_usd,
            fill_count = liquidation_days.fill_count + excluded.fill_count,
            largest_usd = CASE
                WHEN excluded.largest_usd > liquidation_days.largest_usd
                THEN excluded.largest_usd
                ELSE liquidation_days.largest_usd
            END
        """,
        params,
    )
    conn.execute(
        _FOLDABLE_CTE
        + """
        DELETE FROM liquidations
        WHERE trade_id IN (SELECT trade_id FROM foldable)
        """,
        params,
    )
    removed = conn.execute("SELECT changes()").fetchone()
    return int(removed[0] if removed is not None else 0)


def fold_liquidations_if_due() -> None:
    import mayedge.db as db

    now = time.time()
    if now - db._last_liq_fold_at < 3600:
        return
    try:
        fold_liquidations(now_ms=int(now * 1000))
    except Exception:
        logger.exception("failed to fold liquidation days")
        return
    db._last_liq_fold_at = now
