"""The venue's pnl buckets, as answered (docs/portfolio-rules.md H1, H2)."""

from __future__ import annotations

import json
from typing import Any

from mayedge.db import _connect, _lock, _set_meta, reading


def _meta(conn: Any, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row["value"])


def portfolio_put_buckets(
    resolution: str, mode: str, rows: list[tuple[int, dict[str, Any]]]
) -> None:
    """(ts in ms, bucket) pairs. A bucket answered again replaces the stored one."""
    if not rows:
        return
    with _lock:
        conn = _connect()
        conn.executemany(
            "INSERT OR REPLACE INTO portfolio_pnl(resolution, mode, ts, raw) VALUES (?, ?, ?, ?)",
            [(resolution, mode, ts, json.dumps(raw, separators=(",", ":"))) for ts, raw in rows],
        )
        conn.commit()


def portfolio_buckets(resolution: str, mode: str, since_ms: int = 0) -> list[dict[str, Any]]:
    """Stored buckets in time order, each with its timestamp in seconds as the venue gave it."""
    with reading() as conn:
        rows = conn.execute(
            "SELECT raw FROM portfolio_pnl WHERE resolution = ? AND mode = ? AND ts >= ? ORDER BY ts",
            (resolution, mode, since_ms),
        ).fetchall()
    return [json.loads(row["raw"]) for row in rows]


def portfolio_oldest_ms(resolution: str) -> int | None:
    """The oldest bucket stored in both modes at this resolution."""
    with _lock:
        conn = _connect()
        row = conn.execute(
            """
            SELECT MAX(oldest) AS ts FROM (
                SELECT MIN(ts) AS oldest FROM portfolio_pnl WHERE resolution = ? GROUP BY mode
            )
            """,
            (resolution,),
        ).fetchone()
    return None if row is None or row["ts"] is None else int(row["ts"])


def portfolio_backfilled(resolution: str) -> bool:
    with _lock:
        conn = _connect()
        return _meta(conn, f"portfolio_backfilled_{resolution}") is not None


def portfolio_note_backfilled(resolution: str) -> None:
    with _lock:
        conn = _connect()
        _set_meta(conn, f"portfolio_backfilled_{resolution}", "1")
        conn.commit()
