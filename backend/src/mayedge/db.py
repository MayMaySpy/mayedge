"""SQLite persistence for chase-iceberg algo runs and ledgers."""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path

from mayedge.config import settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

_JOURNAL_TABLES = """
CREATE TABLE IF NOT EXISTS journal_fills (
    trade_id TEXT PRIMARY KEY,
    market_index INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    is_maker INTEGER NOT NULL,
    price TEXT NOT NULL,
    size TEXT NOT NULL,
    usd TEXT NOT NULL,
    fee TEXT NOT NULL,
    pnl TEXT NOT NULL,
    kind TEXT NOT NULL,
    ts INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_journal_fills_ts ON journal_fills(market_index, ts);

CREATE TABLE IF NOT EXISTS journal_funding (
    market_index INTEGER NOT NULL,
    ts INTEGER NOT NULL,
    amount TEXT NOT NULL,
    PRIMARY KEY (market_index, ts)
);

CREATE TABLE IF NOT EXISTS journal_notes (
    trip_key TEXT PRIMARY KEY,
    note TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    updated_at INTEGER NOT NULL
);
"""

# The venue's pnl buckets (docs/portfolio-rules.md H1). raw is the bucket as answered.
_PORTFOLIO_TABLES = """
CREATE TABLE IF NOT EXISTS portfolio_pnl (
    resolution TEXT NOT NULL,
    mode TEXT NOT NULL,
    ts INTEGER NOT NULL,
    raw TEXT NOT NULL,
    PRIMARY KEY (resolution, mode, ts)
);
"""

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

CREATE TABLE IF NOT EXISTS liquidation_days (
    day_index INTEGER NOT NULL,
    market_index INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    long_usd REAL NOT NULL,
    short_usd REAL NOT NULL,
    total_usd REAL NOT NULL,
    fill_count INTEGER NOT NULL,
    largest_usd REAL NOT NULL,
    PRIMARY KEY (day_index, market_index)
);

CREATE TABLE IF NOT EXISTS oi_samples (
    market_index INTEGER NOT NULL,
    minute_index INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    oi_usd REAL NOT NULL,
    PRIMARY KEY (market_index, minute_index)
);

CREATE INDEX IF NOT EXISTS idx_oi_samples_minute ON oi_samples(minute_index);

CREATE TABLE IF NOT EXISTS oi_hours (
    hour_index INTEGER NOT NULL,
    market_index INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    oi_high REAL NOT NULL,
    oi_low REAL NOT NULL,
    oi_close REAL NOT NULL,
    PRIMARY KEY (hour_index, market_index)
);

CREATE TABLE IF NOT EXISTS alert_outcomes (
    episode_id TEXT NOT NULL,
    market_index INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    setup TEXT NOT NULL,
    direction TEXT NOT NULL,
    horizon_min INTEGER NOT NULL,
    opened_at INTEGER NOT NULL,
    raw_pct REAL NOT NULL,
    excess_pct REAL NOT NULL,
    hit INTEGER NOT NULL,
    PRIMARY KEY (episode_id, horizon_min)
);

CREATE INDEX IF NOT EXISTS idx_alert_outcomes_opened ON alert_outcomes(opened_at);

CREATE TABLE IF NOT EXISTS alert_rows (
    id TEXT PRIMARY KEY,
    market_index INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    rule TEXT NOT NULL,
    severity INTEGER NOT NULL,
    direction TEXT NOT NULL,
    held TEXT NOT NULL DEFAULT '',
    fired_at INTEGER NOT NULL,
    price REAL NOT NULL,
    facts TEXT NOT NULL DEFAULT '[]',
    left_pct REAL,
    against_pct REAL,
    opened_at INTEGER
);

CREATE INDEX IF NOT EXISTS idx_alert_rows_fired ON alert_rows(fired_at);

CREATE TABLE IF NOT EXISTS funding_samples (
    market_index INTEGER NOT NULL,
    minute_index INTEGER NOT NULL,
    funding REAL NOT NULL,
    PRIMARY KEY (market_index, minute_index)
);

CREATE INDEX IF NOT EXISTS idx_funding_samples_minute ON funding_samples(minute_index);

CREATE TABLE IF NOT EXISTS funding_prints (
    market_index INTEGER NOT NULL,
    hour_index INTEGER NOT NULL,
    rate REAL NOT NULL,
    PRIMARY KEY (market_index, hour_index)
);

CREATE TABLE IF NOT EXISTS funding_days (
    market_index INTEGER NOT NULL,
    day_index INTEGER NOT NULL,
    rate REAL NOT NULL,
    PRIMARY KEY (market_index, day_index)
);
""" + _JOURNAL_TABLES

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

_LIQ_DAYS_TABLE = """
CREATE TABLE IF NOT EXISTS liquidation_days (
    day_index INTEGER NOT NULL,
    market_index INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    long_usd REAL NOT NULL,
    short_usd REAL NOT NULL,
    total_usd REAL NOT NULL,
    fill_count INTEGER NOT NULL,
    largest_usd REAL NOT NULL,
    PRIMARY KEY (day_index, market_index)
)
"""

_last_liq_fold_at = time.time()
_last_oi_fold_at = time.time()
SCHEMA_VERSION = 14


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
    if version < 4:
        conn.execute(
            """
            UPDATE liquidations SET side = CASE
              WHEN side = 'buy' THEN 'sell'
              WHEN side = 'sell' THEN 'buy'
              ELSE side END
            """
        )
    if version < 5:
        conn.execute(_LIQ_DAYS_TABLE)
    if version < 6:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS oi_samples (
                market_index INTEGER NOT NULL,
                minute_index INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                oi_usd REAL NOT NULL,
                PRIMARY KEY (market_index, minute_index)
            );
            CREATE INDEX IF NOT EXISTS idx_oi_samples_minute ON oi_samples(minute_index);
            CREATE TABLE IF NOT EXISTS oi_days (
                day_index INTEGER NOT NULL,
                market_index INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                oi_high REAL NOT NULL,
                oi_low REAL NOT NULL,
                oi_close REAL NOT NULL,
                PRIMARY KEY (day_index, market_index)
            );
            """
        )
    if version < 7:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS alert_outcomes (
                episode_id TEXT NOT NULL,
                market_index INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                setup TEXT NOT NULL,
                direction TEXT NOT NULL,
                horizon_min INTEGER NOT NULL,
                opened_at INTEGER NOT NULL,
                raw_pct REAL NOT NULL,
                excess_pct REAL NOT NULL,
                hit INTEGER NOT NULL,
                PRIMARY KEY (episode_id, horizon_min)
            );
            CREATE INDEX IF NOT EXISTS idx_alert_outcomes_opened ON alert_outcomes(opened_at);
            """
        )
    if version < 8:
        # alert_outcomes stays where it is. Nothing reads it; its rows used the old clock.
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS alert_rows (
                id TEXT PRIMARY KEY,
                market_index INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                rule TEXT NOT NULL,
                severity INTEGER NOT NULL,
                direction TEXT NOT NULL,
                held TEXT NOT NULL DEFAULT '',
                fired_at INTEGER NOT NULL,
                price REAL NOT NULL,
                facts TEXT NOT NULL DEFAULT '[]',
                left_pct REAL,
                against_pct REAL,
                opened_at INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_alert_rows_fired ON alert_rows(fired_at);
            """
        )
    if version < 9:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS funding_samples (
                market_index INTEGER NOT NULL,
                minute_index INTEGER NOT NULL,
                funding REAL NOT NULL,
                PRIMARY KEY (market_index, minute_index)
            );
            CREATE INDEX IF NOT EXISTS idx_funding_samples_minute
                ON funding_samples(minute_index);
            """
        )
    if version < 10:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS funding_prints (
                market_index INTEGER NOT NULL,
                hour_index INTEGER NOT NULL,
                rate REAL NOT NULL,
                PRIMARY KEY (market_index, hour_index)
            )
            """
        )
    if version < 11:
        # Old minutes now fold into hours. A folded day becomes its last hour.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS oi_hours (
                hour_index INTEGER NOT NULL,
                market_index INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                oi_high REAL NOT NULL,
                oi_low REAL NOT NULL,
                oi_close REAL NOT NULL,
                PRIMARY KEY (hour_index, market_index)
            )
            """
        )
        has_days = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'oi_days'"
        ).fetchone()
        if has_days:
            conn.execute(
                """
                INSERT OR IGNORE INTO oi_hours
                    (hour_index, market_index, symbol, oi_high, oi_low, oi_close)
                SELECT day_index * 24 + 23, market_index, symbol, oi_high, oi_low, oi_close
                FROM oi_days
                """
            )
            conn.execute("DROP TABLE oi_days")
    if version < 12:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS funding_days (
                market_index INTEGER NOT NULL,
                day_index INTEGER NOT NULL,
                rate REAL NOT NULL,
                PRIMARY KEY (market_index, day_index)
            )
            """
        )
    if version < 13:
        conn.executescript(_JOURNAL_TABLES)
    if version < 14:
        conn.executescript(_PORTFOLIO_TABLES)
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


def save_book_counters(book: str, id_seq: int, coi_seq: int) -> None:
    """A book's own id and client_order_index counters, under keys no other book writes."""
    with _lock:
        conn = _connect()
        for key, value in ((f"{book}_id_seq", id_seq), (f"{book}_coi_seq", coi_seq)):
            conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )
        conn.commit()


def _has_meta(conn: sqlite3.Connection, key: str) -> bool:
    return conn.execute("SELECT 1 FROM meta WHERE key = ?", (key,)).fetchone() is not None


def _max_run_seq(conn: sqlite3.Connection, id_prefix: str) -> int:
    best = 0
    for row in conn.execute(
        "SELECT algo_id FROM algo_runs WHERE substr(algo_id, 1, ?) = ?",
        (len(id_prefix), id_prefix),
    ):
        try:
            best = max(best, int(str(row["algo_id"])[len(id_prefix) :]))
        except ValueError:
            continue
    return best


def _max_coi_seq(conn: sqlite3.Connection, coi_base: int, coi_end: int) -> int:
    best = 0
    for table in ("algo_clips", "algo_fills"):
        row = conn.execute(
            f"SELECT MAX(client_order_index) AS top FROM {table} "
            "WHERE client_order_index >= ? AND client_order_index < ?",
            (coi_base, coi_end),
        ).fetchone()
        if row and row["top"] is not None:
            best = max(best, int(row["top"]) - coi_base)
    return best


def load_book_counters(
    book: str,
    *,
    id_prefix: str | None = None,
    coi_band: tuple[int, int] | None = None,
) -> dict[str, int]:
    """A book's own counters.

    With id_prefix and coi_band, a book that has never saved its own keys starts above
    the shared id_seq / coi_seq and above every algo id and client_order_index already
    in its rows, and those seeds are saved under its own keys.
    """
    id_key, coi_key = f"{book}_id_seq", f"{book}_coi_seq"
    with _lock:
        conn = _connect()
        if id_prefix is None or coi_band is None:
            return {"id_seq": _meta_int(conn, id_key), "coi_seq": _meta_int(conn, coi_key)}
        seeded = False
        if _has_meta(conn, id_key):
            id_seq = _meta_int(conn, id_key)
        else:
            id_seq = max(
                _meta_int(conn, "id_seq", fallback="id_seq:lighter"),
                _max_run_seq(conn, id_prefix),
            )
            _set_meta(conn, id_key, str(id_seq))
            seeded = True
        if _has_meta(conn, coi_key):
            coi_seq = _meta_int(conn, coi_key)
        else:
            coi_seq = max(
                _meta_int(conn, "coi_seq", fallback="coi_seq:lighter"),
                _max_coi_seq(conn, *coi_band),
            )
            _set_meta(conn, coi_key, str(coi_seq))
            seeded = True
        if seeded:
            conn.commit()
            logger.info("%s counters seeded at id_seq=%s coi_seq=%s", book, id_seq, coi_seq)
        return {"id_seq": id_seq, "coi_seq": coi_seq}


# persist_* import db internals; re-export after they are defined.
from mayedge.persist_algo import (  # noqa: E402
    load_active_runs,
    load_history,
    upsert_run,
)
from mayedge.persist_funding import (  # noqa: E402
    flush_funding,
    flush_funding_prints,
    funding_averages,
    funding_backfill_done,
    funding_days_backfill_done,
    funding_prints_for,
    insert_funding_days,
    insert_missing_funding_prints,
    list_funding,
    mark_funding_backfill_done,
    mark_funding_days_backfill_done,
    recent_funding,
    recent_funding_prints,
)
from mayedge.persist_liq import (  # noqa: E402
    fold_liquidations,
    fold_liquidations_if_due,
    insert_liquidations,
    list_liquidations,
    summarize_liquidations,
)
from mayedge.persist_oi import (  # noqa: E402
    flush_open_interest,
    fold_open_interest,
    fold_open_interest_if_due,
    list_open_interest,
    recent_open_interest,
)

__all__ = [
    "close_db",
    "flush_funding",
    "flush_funding_prints",
    "flush_open_interest",
    "fold_liquidations",
    "fold_liquidations_if_due",
    "fold_open_interest",
    "fold_open_interest_if_due",
    "funding_averages",
    "funding_backfill_done",
    "funding_days_backfill_done",
    "funding_prints_for",
    "init_db",
    "insert_funding_days",
    "insert_liquidations",
    "insert_missing_funding_prints",
    "list_funding",
    "list_liquidations",
    "list_open_interest",
    "load_active_runs",
    "load_book_counters",
    "load_counters",
    "load_history",
    "load_manual_coi_seq",
    "mark_funding_backfill_done",
    "mark_funding_days_backfill_done",
    "recent_funding",
    "recent_funding_prints",
    "recent_open_interest",
    "save_book_counters",
    "save_counters",
    "save_manual_coi_seq",
    "summarize_liquidations",
    "upsert_run",
]
