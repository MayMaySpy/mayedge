"""Liquidation SQLite persistence."""

from __future__ import annotations

import logging
import time
from typing import Any

from mayedge.db import _LIQ_MAX_AGE_MS, _LIQ_MAX_ROWS, _connect, _lock

logger = logging.getLogger(__name__)


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
    _maybe_prune_liquidations()
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


def _maybe_prune_liquidations() -> None:
    import mayedge.db as db

    now = time.time()
    if now - db._last_liq_prune_at < 3600:
        return
    db._last_liq_prune_at = now
    cutoff = int(time.time() * 1000) - _LIQ_MAX_AGE_MS
    with _lock:
        conn = _connect()
        conn.execute("DELETE FROM liquidations WHERE ts < ?", (cutoff,))
        count = conn.execute("SELECT COUNT(*) AS n FROM liquidations").fetchone()["n"]
        if count > _LIQ_MAX_ROWS:
            excess = count - _LIQ_MAX_ROWS
            conn.execute(
                """
                DELETE FROM liquidations WHERE trade_id IN (
                    SELECT trade_id FROM liquidations ORDER BY ts ASC LIMIT ?
                )
                """,
                (excess,),
            )
        conn.commit()
