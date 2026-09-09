from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from mayedge import db as store
from mayedge.config import settings
from mayedge.lighter.liquidations import LiquidationFeed
from mayedge.lighter.models import MarketMeta


def _row(**kwargs: object) -> dict[str, object]:
    base: dict[str, object] = {
        "trade_id": 42,
        "market_index": 1,
        "symbol": "ETH",
        "kind": "liquidation",
        "side": "sell",
        "price": "2000",
        "size": "3",
        "usd_amount": "6000",
        "ts": 1_700_000_000_000,
    }
    base.update(kwargs)
    return base


class LiquidationHydrateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = TemporaryDirectory()
        path = str(Path(self._td.name) / "mayedge.db")
        self._patch = patch.object(settings, "db_path", path)
        self._patch.start()
        store.close_db()
        store.init_db()

    def tearDown(self) -> None:
        store.close_db()
        self._patch.stop()
        self._td.cleanup()

    def test_recent_is_empty_until_hydrate(self) -> None:
        store.insert_liquidations([_row()])
        feed = LiquidationFeed(lambda _msg: None)
        self.assertEqual(feed.recent(), [])
        feed.hydrate()
        rows = feed.recent()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["trade_id"], "42")
        self.assertEqual(rows[0]["timestamp"], 1_700_000_000_000)

    def test_hydrate_dedupes_live_ingest(self) -> None:
        store.insert_liquidations([_row()])
        feed = LiquidationFeed(lambda _msg: None)
        feed.hydrate()
        eth = MarketMeta(1, "ETH", 2, 4, 0.001, 10.0, market_type="perp")
        feed.ingest(
            1,
            [{"trade_id": 42, "price": "2000", "size": "3", "timestamp": 1_700_000_000_000}],
            get_market=lambda _i: eth,
        )
        self.assertEqual(len(feed.recent()), 1)
