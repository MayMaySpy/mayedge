from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from mayedge import db as store
from mayedge.config import settings


class PersistNoVenueTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = TemporaryDirectory()
        path = str(Path(self._td.name) / "mayedge.db")
        self._patch = patch.object(settings, "db_path", path)
        self._patch.start()
        store.close_db()

    def tearDown(self) -> None:
        store.close_db()
        self._patch.stop()
        self._td.cleanup()

    def test_load_counters_falls_back_to_legacy_lighter_keys(self) -> None:
        store.init_db()
        with store._lock:
            conn = store._connect()
            conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?)",
                ("id_seq:lighter", "7"),
            )
            conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?)",
                ("coi_seq:lighter", "11"),
            )
            conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?)",
                ("manual_coi_seq:lighter", "3"),
            )
            conn.commit()
        counters = store.load_counters()
        self.assertEqual(counters["id_seq"], 7)
        self.assertEqual(counters["coi_seq"], 11)
        self.assertEqual(counters["manual_coi_seq"], 3)

    def test_load_counters_prefers_plain_keys(self) -> None:
        store.save_counters(4, 9)
        store.save_manual_coi_seq(2)
        with store._lock:
            conn = store._connect()
            conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?)",
                ("id_seq:lighter", "99"),
            )
            conn.commit()
        counters = store.load_counters()
        self.assertEqual(counters["id_seq"], 4)
        self.assertEqual(counters["coi_seq"], 9)
        self.assertEqual(store.load_manual_coi_seq(), 2)

    def test_load_active_runs_needs_no_venue(self) -> None:
        store.upsert_run(
            {
                "algo_id": "CH-0001",
                "status": "running",
                "market_index": 1,
                "symbol": "ETH",
                "side": "buy",
                "qty": "10",
                "display_qty": "1",
                "offset_bps": "4",
                "price_floor": "90",
                "price_ceiling": "100",
                "remaining": "10",
                "filled": "0",
                "created_at": 1,
            },
            next_clip=1,
            next_fill=1,
            trade_ids=set(),
            trade_qty_by_clip={},
            clips=[],
            fills=[],
        )
        rows = store.load_active_runs(algo_type="chase-iceberg")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["algo_id"], "CH-0001")
        history = store.load_history(10, algo_type="chase-iceberg")
        self.assertEqual(history, [])
