"""Every stored schema version reaches today's schema, and a failed step changes nothing."""

from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from expect_logs import expects_logs

from mayedge import db as store
from mayedge import migrations
from mayedge.config import settings


def _shape(conn: sqlite3.Connection) -> dict[str, object]:
    """Tables with their columns, and index names: what a migration must agree on."""
    tables = [
        str(r[0])
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    shape: dict[str, object] = {
        t: sorted(
            (str(c[1]), str(c[2]), int(c[3])) for c in conn.execute(f"PRAGMA table_info({t})")
        )
        for t in tables
    }
    shape["indexes"] = sorted(
        str(r[0])
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name NOT LIKE 'sqlite_%'"
        )
    )
    return shape


# The oldest file the desk has had: no venue or algo type, liquidations without side.
_LEGACY = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE algo_runs (
    algo_id TEXT PRIMARY KEY, status TEXT NOT NULL, market_index INTEGER NOT NULL,
    symbol TEXT NOT NULL DEFAULT '', reduce_only INTEGER NOT NULL DEFAULT 0, side TEXT,
    qty TEXT, display_qty TEXT, offset_bps TEXT, price_floor TEXT, price_ceiling TEXT,
    remaining TEXT, filled TEXT, quote_action TEXT, reason TEXT, rest_price TEXT,
    rest_qty TEXT, error TEXT, created_at INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0,
    next_clip INTEGER NOT NULL DEFAULT 1, next_fill INTEGER NOT NULL DEFAULT 1,
    trade_qty_by_clip TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE algo_clips (
    algo_id TEXT NOT NULL, seq INTEGER NOT NULL, client_order_index INTEGER NOT NULL,
    order_index INTEGER, price TEXT NOT NULL, qty TEXT NOT NULL,
    filled TEXT NOT NULL DEFAULT '0', status TEXT NOT NULL,
    seen_on_book INTEGER NOT NULL DEFAULT 0, placed_at INTEGER NOT NULL DEFAULT 0,
    closed_at INTEGER, missing_since INTEGER, PRIMARY KEY (algo_id, seq)
);
CREATE TABLE liquidations (
    trade_id INTEGER PRIMARY KEY, market_index INTEGER NOT NULL, symbol TEXT NOT NULL,
    kind TEXT NOT NULL, price TEXT NOT NULL, size TEXT NOT NULL, ts INTEGER NOT NULL
);
INSERT INTO algo_runs (algo_id, status, market_index) VALUES ('chase-1', 'stopped', 1);
"""


class MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = TemporaryDirectory()
        self.path = str(Path(self._td.name) / "mayedge.db")
        self._patch = patch.object(settings, "db_path", self.path)
        self._patch.start()
        store.close_db()

    def tearDown(self) -> None:
        store.close_db()
        self._patch.stop()
        self._td.cleanup()

    def _fresh_shape(self) -> dict[str, object]:
        path = str(Path(self._td.name) / "fresh.db")
        with patch.object(settings, "db_path", path):
            store.close_db()
            store.init_db()
            with store._lock:
                shape = _shape(store._connect())
            store.close_db()
        return shape

    def test_steps_are_numbered_one_by_one_up_to_the_schema_version(self) -> None:
        self.assertEqual(
            [s.version for s in migrations.STEPS], list(range(1, len(migrations.STEPS) + 1))
        )
        self.assertEqual(migrations.LATEST, store.SCHEMA_VERSION)

    @expects_logs()
    def test_the_oldest_file_reaches_todays_schema(self) -> None:
        conn = sqlite3.connect(self.path)
        conn.executescript(_LEGACY)
        conn.commit()
        conn.close()

        store.init_db()
        with store._lock:
            conn = store._connect()
            shape = _shape(conn)
            run = conn.execute("SELECT algo_type, venue, params_json FROM algo_runs").fetchone()
            version = migrations.stored_version(conn)
        store.close_db()

        self.assertEqual(shape, self._fresh_shape())
        self.assertEqual(tuple(run), ("chase-iceberg", "lighter", "{}"))
        self.assertEqual(version, store.SCHEMA_VERSION)

    def test_every_stored_version_reaches_todays_schema(self) -> None:
        fresh = self._fresh_shape()
        for start in range(store.SCHEMA_VERSION):
            with self.subTest(start=start):
                store.init_db()
                with store._lock:
                    conn = store._connect()
                    store._set_meta(conn, "schema_version", str(start))
                    conn.commit()
                    store._migrate(conn)
                    self.assertEqual(_shape(conn), fresh)
                    self.assertEqual(migrations.stored_version(conn), store.SCHEMA_VERSION)
                store.close_db()

    def test_open_interest_days_become_their_last_hour(self) -> None:
        store.init_db()
        with store._lock:
            conn = store._connect()
            migrations._v6(conn)
            conn.execute("INSERT INTO oi_days VALUES (100, 1, 'BTC', 3.0, 1.0, 2.0)")
            store._set_meta(conn, "schema_version", "10")
            conn.commit()
            store._migrate(conn)
            row = conn.execute("SELECT hour_index, oi_close FROM oi_hours").fetchone()
            days = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'oi_days'"
            ).fetchone()
        self.assertEqual(tuple(row), (100 * 24 + 23, 2.0))
        self.assertIsNone(days)

    def test_a_failed_step_leaves_the_file_at_the_step_before(self) -> None:
        store.init_db()

        def half_then_fail(conn: sqlite3.Connection) -> None:
            conn.execute("INSERT INTO meta(key, value) VALUES('half', '1')")
            raise RuntimeError("disk gone")

        steps = (
            *migrations.STEPS,
            migrations.Step(store.SCHEMA_VERSION + 1, "breaks", half_then_fail),
        )
        with store._lock:
            conn = store._connect()
            with self.assertRaises(RuntimeError):
                migrations.migrate(conn, steps)
            half = conn.execute("SELECT 1 FROM meta WHERE key = 'half'").fetchone()
            version = migrations.stored_version(conn)
        self.assertIsNone(half)
        self.assertEqual(version, store.SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
