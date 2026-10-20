"""Journal SQLite rows: fills, funding, and notes. Round trips are not stored."""

from __future__ import annotations

import json
import time
from typing import Any

from mayedge.db import _connect, _lock, _set_meta

_OLDEST = "journal_oldest_ts"
_SYNCED = "journal_last_synced_at"


def _meta(conn: Any, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row["value"])


def journal_known_trade_ids(trade_ids: list[str]) -> set[str]:
    if not trade_ids:
        return set()
    marks = ",".join("?" for _ in trade_ids)
    with _lock:
        conn = _connect()
        rows = conn.execute(
            f"SELECT trade_id FROM journal_fills WHERE trade_id IN ({marks})",
            trade_ids,
        )
        return {str(row["trade_id"]) for row in rows}


def journal_insert_fills(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with _lock:
        conn = _connect()
        conn.executemany(
            """
            INSERT OR IGNORE INTO journal_fills(
                trade_id, market_index, symbol, side, is_maker, price, size, usd, fee, pnl, kind, ts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    str(row["trade_id"]),
                    int(row["market_index"]),
                    str(row["symbol"]),
                    str(row["side"]),
                    1 if row["is_maker"] else 0,
                    str(row["price"]),
                    str(row["size"]),
                    str(row["usd"]),
                    str(row["fee"]),
                    str(row["pnl"]),
                    str(row["kind"]),
                    int(row["ts"]),
                )
                for row in rows
            ],
        )
        conn.commit()


def journal_known_funding(keys: list[tuple[int, int]]) -> set[tuple[int, int]]:
    if not keys:
        return set()
    found: set[tuple[int, int]] = set()
    with _lock:
        conn = _connect()
        for market_index, ts in keys:
            row = conn.execute(
                "SELECT 1 FROM journal_funding WHERE market_index = ? AND ts = ?",
                (market_index, ts),
            ).fetchone()
            if row is not None:
                found.add((market_index, ts))
    return found


def journal_insert_funding(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with _lock:
        conn = _connect()
        conn.executemany(
            """
            INSERT OR IGNORE INTO journal_funding(market_index, ts, amount)
            VALUES (?, ?, ?)
            """,
            [(int(row["market_index"]), int(row["ts"]), str(row["amount"])) for row in rows],
        )
        conn.commit()


def journal_oldest_ts() -> int | None:
    with _lock:
        conn = _connect()
        raw = _meta(conn, _OLDEST)
    return None if raw is None else int(raw)


def journal_note_oldest(ts: int) -> None:
    """Keep the earliest timestamp a backfill actually reached."""
    with _lock:
        conn = _connect()
        raw = _meta(conn, _OLDEST)
        if raw is not None and int(raw) <= ts:
            return
        _set_meta(conn, _OLDEST, str(ts))
        conn.commit()


def journal_backfilled(kind: str) -> bool:
    """A walk of ``kind`` (trades or funding) once reached the venue's oldest page."""
    with _lock:
        conn = _connect()
        done = _meta(conn, f"journal_backfilled_{kind}") is not None
        # Desks that finished a trades backfill before this marker existed.
        if not done and kind == "trades":
            done = _meta(conn, _OLDEST) is not None
    return done


def journal_note_backfilled(kind: str) -> None:
    with _lock:
        conn = _connect()
        _set_meta(conn, f"journal_backfilled_{kind}", "1")
        conn.commit()


def journal_last_synced_at() -> int | None:
    with _lock:
        conn = _connect()
        raw = _meta(conn, _SYNCED)
    return None if raw is None else int(raw)


def journal_note_synced(ts: int | None = None) -> None:
    with _lock:
        conn = _connect()
        _set_meta(conn, _SYNCED, str(int(time.time()) if ts is None else ts))
        conn.commit()


def journal_load_fills() -> list[dict[str, Any]]:
    with _lock:
        conn = _connect()
        rows = conn.execute("SELECT * FROM journal_fills ORDER BY ts, trade_id").fetchall()
    return [dict(row) for row in rows]


def journal_load_funding() -> list[dict[str, Any]]:
    with _lock:
        conn = _connect()
        rows = conn.execute(
            "SELECT * FROM journal_funding ORDER BY ts, market_index"
        ).fetchall()
    return [dict(row) for row in rows]


def journal_load_links() -> dict[str, str]:
    with _lock:
        conn = _connect()
        rows = conn.execute(
            "SELECT trade_id, algo_id FROM algo_trade_ids ORDER BY algo_id"
        ).fetchall()
    links: dict[str, str] = {}
    for row in rows:
        links.setdefault(str(row["trade_id"]), str(row["algo_id"]))
    return links


def journal_load_planner_risk() -> dict[str, tuple[str, str]]:
    """Entry and the stop stored when the Planner run started. Missing means R is n/a."""
    with _lock:
        conn = _connect()
        rows = conn.execute(
            "SELECT algo_id, params_json FROM algo_runs WHERE algo_id LIKE 'PL-%'"
        ).fetchall()
    out: dict[str, tuple[str, str]] = {}
    for row in rows:
        try:
            raw = json.loads(row["params_json"] or "{}")
        except json.JSONDecodeError:
            continue
        runtime = raw.get("runtime") if isinstance(raw, dict) else None
        planner = runtime.get("planner") if isinstance(runtime, dict) else None
        plan = planner.get("plan") if isinstance(planner, dict) else None
        if not isinstance(plan, dict):
            continue
        entry, stop = plan.get("entry"), plan.get("stop")
        if entry in (None, "") or stop in (None, ""):
            continue
        out[str(row["algo_id"])] = (str(entry), str(stop))
    return out


def journal_put_note(trip_key: str, note: str, tags: list[str]) -> None:
    with _lock:
        conn = _connect()
        conn.execute(
            """
            INSERT INTO journal_notes(trip_key, note, tags, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(trip_key) DO UPDATE SET
                note=excluded.note, tags=excluded.tags, updated_at=excluded.updated_at
            """,
            (trip_key, note, json.dumps(tags), int(time.time())),
        )
        conn.commit()


def journal_load_notes() -> dict[str, dict[str, Any]]:
    with _lock:
        conn = _connect()
        rows = conn.execute("SELECT * FROM journal_notes").fetchall()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        try:
            tags = json.loads(row["tags"] or "[]")
        except json.JSONDecodeError:
            tags = []
        out[str(row["trip_key"])] = {
            "note": str(row["note"] or ""),
            "tags": tags if isinstance(tags, list) else [],
            "updated_at": int(row["updated_at"]),
        }
    return out
