from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
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
        self.assertEqual(rows[0]["trade_id"], "1:liquidation:t42")
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
        self.assertEqual(feed.recent()[0]["fill_count"], 1)

    def test_hydrate_groups_fills_of_one_order(self) -> None:
        gid = "1:liquidation:555"
        store.insert_liquidations(
            [
                _row(trade_id=10, group_id=gid, size="1", usd_amount="2000"),
                _row(trade_id=11, group_id=gid, size="2", usd_amount="4000"),
            ]
        )
        feed = LiquidationFeed(lambda _msg: None)
        feed.hydrate()
        rows = feed.recent()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["trade_id"], gid)
        self.assertEqual(rows[0]["fill_count"], 2)
        self.assertEqual(float(rows[0]["size"]), 3)
        self.assertEqual(float(rows[0]["usd_amount"]), 6000)


class LiquidationGroupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.out: list[dict[str, Any]] = []
        self.feed = LiquidationFeed(self.out.append, persist=False)
        self.eth = MarketMeta(1, "ETH", 2, 4, 0.001, 10.0, market_type="perp")

    def _fill(self, trade_id: int, *, ask_id: int, size: str = "0.1", **extra: object) -> dict[str, Any]:
        row: dict[str, Any] = {
            "trade_id": trade_id,
            "price": "100",
            "size": size,
            "usd_amount": str(float(size) * 100),
            "timestamp": 1_700_000_000_000,
            "is_maker_ask": False,
            "ask_id": ask_id,
            "bid_id": 9_000 + trade_id,
            "type": "liquidation",
        }
        row.update(extra)
        return row

    def test_groups_taker_order_fills(self) -> None:
        fills = [self._fill(100 + i, ask_id=555) for i in range(14)]
        self.feed.ingest(1, fills, get_market=lambda _i: self.eth)
        rows = self.feed.recent()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["fill_count"], 14)
        self.assertAlmostEqual(float(rows[0]["size"]), 1.4)
        self.assertAlmostEqual(float(rows[0]["usd_amount"]), 140)
        self.assertEqual(rows[0]["price"], "100")
        items = [m for m in self.out if m.get("type") == "liquidations"][-1]["items"]
        self.assertEqual(len(items), 1)

    def test_split_distinct_taker_orders(self) -> None:
        self.feed.ingest(
            1,
            [self._fill(1, ask_id=1), self._fill(2, ask_id=556)],
            get_market=lambda _i: self.eth,
        )
        self.assertEqual(len(self.feed.recent()), 2)

    def test_later_fills_merge_into_same_group(self) -> None:
        self.feed.ingest(1, [self._fill(1, ask_id=555, size="1")], get_market=lambda _i: self.eth)
        self.feed.ingest(1, [self._fill(2, ask_id=555, size="3")], get_market=lambda _i: self.eth)
        rows = self.feed.recent()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["fill_count"], 2)
        self.assertAlmostEqual(float(rows[0]["size"]), 4)
        self.assertAlmostEqual(float(rows[0]["usd_amount"]), 400)

    def test_snapshot_ingest_does_not_broadcast(self) -> None:
        fills = [self._fill(100 + i, ask_id=100 + i) for i in range(8)]
        self.feed.ingest(1, fills, get_market=lambda _i: self.eth, snapshot=True)
        self.assertEqual(len(self.feed.recent()), 8)
        self.assertFalse(any(m.get("type") == "liquidations" for m in self.out))

    def test_buy_taker_groups_on_bid_id(self) -> None:
        fills = [
            self._fill(10 + i, ask_id=800 + i, bid_id=777, is_maker_ask=True)
            for i in range(3)
        ]
        self.feed.ingest(1, fills, get_market=lambda _i: self.eth)
        rows = self.feed.recent()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["trade_id"], "1:liquidation:777")
        self.assertEqual(rows[0]["fill_count"], 3)


class LiquidationSummaryTests(unittest.TestCase):
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

    def test_splits_long_and_short_usd_per_market(self) -> None:
        now = 1_700_000_000_000
        store.insert_liquidations(
            [
                _row(trade_id=1, symbol="ETH", market_index=1, side="sell", usd_amount="4000", ts=now),
                _row(trade_id=2, symbol="ETH", market_index=1, side="sell", usd_amount="2000", ts=now),
                _row(trade_id=3, symbol="ETH", market_index=1, side="buy", usd_amount="1000", ts=now),
                _row(trade_id=4, symbol="BTC", market_index=2, side="buy", usd_amount="5000", ts=now),
            ]
        )
        rows = store.summarize_liquidations(since_ms=now - 60_000)
        by_sym = {r["symbol"]: r for r in rows}
        self.assertEqual(by_sym["ETH"]["long_usd"], 6000.0)
        self.assertEqual(by_sym["ETH"]["short_usd"], 1000.0)
        self.assertEqual(by_sym["ETH"]["total_usd"], 7000.0)
        self.assertEqual(by_sym["ETH"]["fill_count"], 3)
        self.assertEqual(by_sym["ETH"]["market_index"], 1)
        self.assertEqual(by_sym["BTC"]["long_usd"], 0.0)
        self.assertEqual(by_sym["BTC"]["short_usd"], 5000.0)
        self.assertEqual(by_sym["BTC"]["total_usd"], 5000.0)

    def test_excludes_fills_before_the_window(self) -> None:
        now = 1_700_000_000_000
        store.insert_liquidations(
            [
                _row(trade_id=1, symbol="ETH", usd_amount="9000", ts=now - 120_000),
                _row(trade_id=2, symbol="ETH", usd_amount="1000", ts=now),
            ]
        )
        rows = store.summarize_liquidations(since_ms=now - 60_000)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["total_usd"], 1000.0)
        self.assertEqual(rows[0]["fill_count"], 1)

    def test_summary_window_is_hours_back_from_now(self) -> None:
        from mayedge.persist_liq import liquidation_summary_since_ms

        self.assertEqual(liquidation_summary_since_ms(24, now_ms=1_700_000_000_000), 1_699_913_600_000)
        self.assertEqual(liquidation_summary_since_ms(1, now_ms=1_700_000_000_000), 1_699_996_400_000)
        with self.assertRaises(ValueError):
            liquidation_summary_since_ms(2, now_ms=1_700_000_000_000)

