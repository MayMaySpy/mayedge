"""Numbered schema steps for the desk database.

`db._SCHEMA` creates today's base tables with IF NOT EXISTS; these steps take an older
file up to date. Each step's SQL is frozen as it was when the step landed: never edit
a step that has shipped, add the next number. A step and its schema_version write
commit together, so a crash in the middle leaves the file at the step before it.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

Apply = Callable[[sqlite3.Connection], None]


@dataclass(frozen=True, slots=True)
class Step:
    version: int
    name: str
    apply: Apply


def _run(conn: sqlite3.Connection, script: str) -> None:
    """Run each statement with execute, so the step stays inside its transaction."""
    for statement in script.split(";"):
        if statement.strip():
            conn.execute(statement)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _liquidation_columns(conn: sqlite3.Connection) -> None:
    cols = _columns(conn, "liquidations")
    if not cols:
        _run(
            conn,
            """
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
            """,
        )
        cols = _columns(conn, "liquidations")
    for name, ddl in (
        ("side", "side TEXT"),
        ("usd_amount", "usd_amount TEXT"),
        ("group_id", "group_id TEXT"),
    ):
        if name not in cols:
            logger.warning("liquidations: adding missing column %s", name)
            conn.execute(f"ALTER TABLE liquidations ADD COLUMN {ddl}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_liq_ts ON liquidations(ts)")


def _v1(conn: sqlite3.Connection) -> None:
    _liquidation_columns(conn)
    if "venue" not in _columns(conn, "algo_runs"):
        conn.execute("ALTER TABLE algo_runs ADD COLUMN venue TEXT NOT NULL DEFAULT 'lighter'")


def _v2(conn: sqlite3.Connection) -> None:
    run_cols = _columns(conn, "algo_runs")
    if "algo_type" not in run_cols:
        conn.execute(
            "ALTER TABLE algo_runs ADD COLUMN algo_type TEXT NOT NULL DEFAULT 'chase-iceberg'"
        )
    if "params_json" not in run_cols:
        conn.execute("ALTER TABLE algo_runs ADD COLUMN params_json TEXT NOT NULL DEFAULT '{}'")
    if "side" not in _columns(conn, "algo_clips"):
        conn.execute("ALTER TABLE algo_clips ADD COLUMN side TEXT")


def _v3(conn: sqlite3.Connection) -> None:
    _liquidation_columns(conn)


def _v4(conn: sqlite3.Connection) -> None:
    # Not idempotent: it may run once only, which the shared commit with the version makes so.
    conn.execute(
        """
        UPDATE liquidations SET side = CASE
          WHEN side = 'buy' THEN 'sell'
          WHEN side = 'sell' THEN 'buy'
          ELSE side END
        """
    )


def _v5(conn: sqlite3.Connection) -> None:
    _run(
        conn,
        """
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
        """,
    )


def _v6(conn: sqlite3.Connection) -> None:
    _run(
        conn,
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
        )
        """,
    )


def _v7(conn: sqlite3.Connection) -> None:
    _run(
        conn,
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
        CREATE INDEX IF NOT EXISTS idx_alert_outcomes_opened ON alert_outcomes(opened_at)
        """,
    )


def _v8(conn: sqlite3.Connection) -> None:
    # alert_outcomes stays where it is. Nothing reads it; its rows used the old clock.
    _run(
        conn,
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
        CREATE INDEX IF NOT EXISTS idx_alert_rows_fired ON alert_rows(fired_at)
        """,
    )


def _v9(conn: sqlite3.Connection) -> None:
    _run(
        conn,
        """
        CREATE TABLE IF NOT EXISTS funding_samples (
            market_index INTEGER NOT NULL,
            minute_index INTEGER NOT NULL,
            funding REAL NOT NULL,
            PRIMARY KEY (market_index, minute_index)
        );
        CREATE INDEX IF NOT EXISTS idx_funding_samples_minute ON funding_samples(minute_index)
        """,
    )


def _v10(conn: sqlite3.Connection) -> None:
    _run(
        conn,
        """
        CREATE TABLE IF NOT EXISTS funding_prints (
            market_index INTEGER NOT NULL,
            hour_index INTEGER NOT NULL,
            rate REAL NOT NULL,
            PRIMARY KEY (market_index, hour_index)
        )
        """,
    )


def _v11(conn: sqlite3.Connection) -> None:
    # Old minutes now fold into hours. A folded day becomes its last hour.
    _run(
        conn,
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
        """,
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


def _v12(conn: sqlite3.Connection) -> None:
    _run(
        conn,
        """
        CREATE TABLE IF NOT EXISTS funding_days (
            market_index INTEGER NOT NULL,
            day_index INTEGER NOT NULL,
            rate REAL NOT NULL,
            PRIMARY KEY (market_index, day_index)
        )
        """,
    )


def _v13(conn: sqlite3.Connection) -> None:
    _run(
        conn,
        """
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
        )
        """,
    )


def _v14(conn: sqlite3.Connection) -> None:
    # The venue's pnl buckets (docs/portfolio-rules.md H1). raw is the bucket as answered.
    _run(
        conn,
        """
        CREATE TABLE IF NOT EXISTS portfolio_pnl (
            resolution TEXT NOT NULL,
            mode TEXT NOT NULL,
            ts INTEGER NOT NULL,
            raw TEXT NOT NULL,
            PRIMARY KEY (resolution, mode, ts)
        )
        """,
    )


def _v15(conn: sqlite3.Connection) -> None:
    # A closed Round trip's Excursion, read once from candles (docs/journal-rules.md).
    _run(
        conn,
        """
        CREATE TABLE IF NOT EXISTS journal_excursions (
            trip_key TEXT PRIMARY KEY,
            sig TEXT NOT NULL,
            resolution TEXT NOT NULL,
            mae_pct TEXT,
            mfe_pct TEXT,
            mae_usd TEXT,
            mfe_usd TEXT,
            computed_at INTEGER NOT NULL
        )
        """,
    )


STEPS: tuple[Step, ...] = (
    Step(1, "liquidation columns, algo venue", _v1),
    Step(2, "algo type, params and clip side", _v2),
    Step(3, "liquidation columns again", _v3),
    Step(4, "liquidation sides flipped to the forced side", _v4),
    Step(5, "liquidation days", _v5),
    Step(6, "open interest samples and days", _v6),
    Step(7, "alert outcomes", _v7),
    Step(8, "alert rows", _v8),
    Step(9, "funding estimates", _v9),
    Step(10, "funding prints", _v10),
    Step(11, "open interest hours replace days", _v11),
    Step(12, "funding days", _v12),
    Step(13, "journal", _v13),
    Step(14, "portfolio pnl buckets", _v14),
    Step(15, "journal excursions", _v15),
)

LATEST = STEPS[-1].version


def stored_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    return int(row[0]) if row else 0


def migrate(conn: sqlite3.Connection, steps: tuple[Step, ...] = STEPS) -> int:
    """Apply every step above the stored version, one transaction each. Returns the version."""
    version = stored_version(conn)
    conn.commit()
    for step in steps:
        if step.version <= version:
            continue
        conn.execute("BEGIN")
        try:
            step.apply(conn)
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(step.version),),
            )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        version = step.version
        logger.info("sqlite schema step %s: %s", step.version, step.name)
    return version
