"""SQLite persistence for chase-iceberg algo runs and ledgers."""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

from mayedge.config import settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS algo_runs (
    algo_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    market_index INTEGER NOT NULL,
    symbol TEXT NOT NULL DEFAULT '',
    reduce_only INTEGER NOT NULL DEFAULT 0,
    side TEXT,
    qty TEXT,
    display_qty TEXT,
    offset_bps TEXT,
    price_floor TEXT,
    price_ceiling TEXT,
    remaining TEXT,
    filled TEXT,
    quote_action TEXT,
    reason TEXT,
    rest_price TEXT,
    rest_qty TEXT,
    error TEXT,
    created_at INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    next_clip INTEGER NOT NULL DEFAULT 1,
    next_fill INTEGER NOT NULL DEFAULT 1,
    trade_qty_by_clip TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS algo_clips (
    algo_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    client_order_index INTEGER NOT NULL,
    order_index INTEGER,
    price TEXT NOT NULL,
    qty TEXT NOT NULL,
    filled TEXT NOT NULL DEFAULT '0',
    status TEXT NOT NULL,
    seen_on_book INTEGER NOT NULL DEFAULT 0,
    placed_at INTEGER NOT NULL DEFAULT 0,
    closed_at INTEGER,
    missing_since INTEGER,
    PRIMARY KEY (algo_id, seq),
    FOREIGN KEY (algo_id) REFERENCES algo_runs(algo_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS algo_fills (
    algo_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    clip_seq INTEGER NOT NULL,
    price TEXT NOT NULL,
    qty TEXT NOT NULL,
    ts INTEGER NOT NULL,
    order_index INTEGER,
    client_order_index INTEGER,
    PRIMARY KEY (algo_id, seq),
    FOREIGN KEY (algo_id) REFERENCES algo_runs(algo_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS algo_trade_ids (
    algo_id TEXT NOT NULL,
    trade_id INTEGER NOT NULL,
    PRIMARY KEY (algo_id, trade_id),
    FOREIGN KEY (algo_id) REFERENCES algo_runs(algo_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_algo_runs_active
    ON algo_runs(archived, status, created_at);

CREATE TABLE IF NOT EXISTS liquidations (
    trade_id INTEGER PRIMARY KEY,
    market_index INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    kind TEXT NOT NULL,
    side TEXT,
    price TEXT NOT NULL,
    size TEXT NOT NULL,
    usd_amount TEXT,
    ts INTEGER NOT NULL,
    group_id TEXT
);
"""

_LIQ_TABLE = """
CREATE TABLE liquidations (
    trade_id INTEGER PRIMARY KEY,
    market_index INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    kind TEXT NOT NULL,
    side TEXT,
    price TEXT NOT NULL,
    size TEXT NOT NULL,
    usd_amount TEXT,
    ts INTEGER NOT NULL,
    group_id TEXT
)
"""

_LIQ_MAX_ROWS = 50_000
_LIQ_MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000
_last_liq_prune_at = 0.0
SCHEMA_VERSION = 3


def _meta_int(
    conn: sqlite3.Connection,
    key: str,
    default: int = 0,
    *,
    fallback: str | None = None,
) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if row:
        return int(row["value"])
    if fallback:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (fallback,)).fetchone()
        if row:
            return int(row["value"])
    return default


def _set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def _ensure_liquidations(conn: sqlite3.Connection) -> None:
    """Create liquidations table; additive column repair only (no DROP on live DB)."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(liquidations)")}
    if not cols:
        conn.execute(_LIQ_TABLE)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(liquidations)")}
    required: dict[str, str] = {
        "side": "side TEXT",
        "usd_amount": "usd_amount TEXT",
        "group_id": "group_id TEXT",
    }
    for name, ddl in required.items():
        if name not in cols:
            logger.warning("liquidations: adding missing column %s", name)
            conn.execute(f"ALTER TABLE liquidations ADD COLUMN {ddl}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_liq_ts ON liquidations(ts)")


def _ensure_algo_venue(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(algo_runs)")}
    if "venue" not in cols:
        conn.execute("ALTER TABLE algo_runs ADD COLUMN venue TEXT NOT NULL DEFAULT 'lighter'")


def _ensure_algo_mm_columns(conn: sqlite3.Connection) -> None:
    run_cols = {row[1] for row in conn.execute("PRAGMA table_info(algo_runs)")}
    if "algo_type" not in run_cols:
        conn.execute(
            "ALTER TABLE algo_runs ADD COLUMN algo_type TEXT NOT NULL DEFAULT 'chase-iceberg'"
        )
    if "params_json" not in run_cols:
        conn.execute("ALTER TABLE algo_runs ADD COLUMN params_json TEXT NOT NULL DEFAULT '{}'")
    clip_cols = {row[1] for row in conn.execute("PRAGMA table_info(algo_clips)")}
    if "side" not in clip_cols:
        conn.execute("ALTER TABLE algo_clips ADD COLUMN side TEXT")


def _migrate(conn: sqlite3.Connection) -> None:
    version = _meta_int(conn, "schema_version", 0)
    if version >= SCHEMA_VERSION:
        return
    if version < 1:
        _ensure_liquidations(conn)
        _ensure_algo_venue(conn)
    if version < 2:
        _ensure_algo_mm_columns(conn)
    if version < 3:
        _ensure_liquidations(conn)
    _set_meta(conn, "schema_version", str(SCHEMA_VERSION))
    logger.info("sqlite schema migrated to version %s", SCHEMA_VERSION)

def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is not None:
        return _conn
    path = Path(settings.db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    _migrate(conn)
    conn.commit()
    _conn = conn
    logger.info("sqlite opened at %s", path.resolve())
    return conn


def init_db() -> None:
    with _lock:
        _connect()


def close_db() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


def save_counters(id_seq: int, coi_seq: int) -> None:
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("id_seq", str(id_seq)),
        )
        conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("coi_seq", str(coi_seq)),
        )
        conn.commit()


def load_counters() -> dict[str, int]:
    with _lock:
        conn = _connect()
        return {
            "id_seq": _meta_int(conn, "id_seq", fallback="id_seq:lighter"),
            "coi_seq": _meta_int(conn, "coi_seq", fallback="coi_seq:lighter"),
            "manual_coi_seq": _meta_int(conn, "manual_coi_seq", fallback="manual_coi_seq:lighter"),
        }


def save_manual_coi_seq(seq: int) -> None:
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("manual_coi_seq", str(seq)),
        )
        conn.commit()


def load_manual_coi_seq() -> int:
    with _lock:
        conn = _connect()
        return _meta_int(conn, "manual_coi_seq", fallback="manual_coi_seq:lighter")


# persist_* import db internals; re-export after they are defined.
from mayedge.persist_algo import (  # noqa: E402
    load_active_runs,
    load_history,
    upsert_run,
)
from mayedge.persist_liq import (  # noqa: E402
    insert_liquidations,
    list_liquidations,
)

__all__ = [
    "close_db",
    "init_db",
    "insert_liquidations",
    "list_liquidations",
    "load_active_runs",
    "load_counters",
    "load_history",
    "load_manual_coi_seq",
    "save_counters",
    "save_manual_coi_seq",
    "upsert_run",
]
