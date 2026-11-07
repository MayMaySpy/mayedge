"""The Setup record (docs/setup-rules.md R1–R3). One row per Setup from when it is first listed."""

from __future__ import annotations

import json

from mayedge.db import _connect, _lock, reading
from mayedge.setups import Setup

# R3.
KEEP_MS = 365 * 86_400_000

Key = tuple[int, str]


def setups_listed_since(since_ms: int) -> dict[Key, int]:
    """Rows still listed at a rebuild at or after ``since_ms``, by Market and kind. R2 at boot."""
    with reading() as conn:
        found = conn.execute(
            "SELECT id, market_index, kind FROM setup_rows WHERE last_at >= ? ORDER BY last_at",
            (int(since_ms),),
        ).fetchall()
    return {(int(r["market_index"]), str(r["kind"])): int(r["id"]) for r in found}


def record_setups(board: list[Setup], listed: dict[Key, int], *, now_ms: int) -> dict[Key, int]:
    """R1, R2. A Setup still listed keeps its row; a new one is written. Returns the new map."""
    out: dict[Key, int] = {}
    with _lock:
        conn = _connect()
        try:
            for s in board:
                key = (s.market_index, s.kind)
                row_id = listed.get(key)
                if row_id is not None:
                    conn.execute("UPDATE setup_rows SET last_at = ? WHERE id = ?", (now_ms, row_id))
                    out[key] = row_id
                    continue
                cur = conn.execute(
                    """
                    INSERT INTO setup_rows
                        (kind, market_index, symbol, direction, size, price, note, facts,
                         first_at, last_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        s.kind,
                        s.market_index,
                        s.symbol,
                        s.direction,
                        s.size,
                        s.price,
                        s.note,
                        json.dumps(s.facts, ensure_ascii=False),
                        now_ms,
                        now_ms,
                    ),
                )
                out[key] = int(cur.lastrowid or 0)
            conn.execute("DELETE FROM setup_rows WHERE last_at < ?", (now_ms - KEEP_MS,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return out
