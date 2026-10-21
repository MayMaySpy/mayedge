"""Order book merge / sort helpers used by the Lighter gateway."""

from __future__ import annotations

import asyncio
import unittest

from expect_logs import expects_logs

from mayedge.lighter.gateway import LighterGateway
from mayedge.lighter.models import MarketMeta, OrderBookLevel
from mayedge.lighter.order_book import OrderBookFeed


def L(price: str, size: str) -> OrderBookLevel:
    return OrderBookLevel(price=price, size=size)


class TestOrderBookMerge(unittest.TestCase):
    def test_snapshot_sorted_and_capped(self) -> None:
        levels = [L("100", "1"), L("102", "2"), L("101", "3"), L("99", "0")]
        bids = OrderBookFeed.sorted_side(levels, bids=True, depth=2)
        self.assertEqual([(b.price, b.size) for b in bids], [("102", "2"), ("101", "3")])

        asks = OrderBookFeed.sorted_side(levels, bids=False, depth=2)
        self.assertEqual([(a.price, a.size) for a in asks], [("100", "1"), ("101", "3")])

    def test_delta_upsert_and_remove(self) -> None:
        existing = [L("100", "1"), L("99", "2"), L("98", "3")]
        updates = [L("99", "0"), L("101", "4"), L("100", "5")]
        bids = OrderBookFeed.merge_side(existing, updates, bids=True, depth=10)
        self.assertEqual(
            [(b.price, b.size) for b in bids],
            [("101", "4"), ("100", "5"), ("98", "3")],
        )

    def test_depth_cap_keeps_best(self) -> None:
        existing = [L(str(i), "1") for i in range(10, 0, -1)]
        bids = OrderBookFeed.merge_side(existing, [L("11", "1")], bids=True, depth=3)
        self.assertEqual([b.price for b in bids], ["11", "10", "9"])

    def test_default_depth_keeps_far_levels(self) -> None:
        levels = [L(str(1000 - i), "1") for i in range(180)]
        bids = OrderBookFeed.sorted_side(levels, bids=True)
        self.assertEqual(len(bids), 180)

    def test_delta_payload_seq_chains(self) -> None:
        feed = OrderBookFeed(lambda _msg: None)
        payload = feed.delta_payload(1, {"100": "1"}, {"101": "2"}, 123)
        self.assertEqual(payload["type"], "order_book_delta")
        self.assertEqual(payload["prev_seq"], 0)
        self.assertEqual(payload["seq"], 1)
        self.assertEqual(feed._book_seq[1], 1)
        payload2 = feed.delta_payload(1, {"100": "0"}, {}, None)
        self.assertEqual(payload2["prev_seq"], 1)
        self.assertEqual(payload2["seq"], 2)


_SNAP = {
    "type": "subscribed/order_book",
    "channel": "order_book:120",
    "order_book": {
        "bids": [{"price": "1", "size": "2"}],
        "asks": [{"price": "3", "size": "4"}],
    },
}


class TestOrderBookCurrentMarket(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_dropped_when_current_unset(self) -> None:
        feed = OrderBookFeed(lambda _msg: None)
        await feed.handle_message(_SNAP)
        self.assertFalse(feed.has_book(120))

    async def test_unparsed_channel_does_not_fall_back_to_current(self) -> None:
        feed = OrderBookFeed(lambda _msg: None)
        feed.set_current_market(120)
        await feed.handle_message(
            {
                "type": "subscribed/order_book",
                "channel": "order_book",
                "order_book": {
                    "bids": [{"price": "1", "size": "2"}],
                    "asks": [{"price": "3", "size": "4"}],
                },
            }
        )
        self.assertFalse(feed.has_book(120))

    async def test_tier2_channel_is_the_market_index(self) -> None:
        feed = OrderBookFeed(lambda _msg: None)
        feed.set_current_market(120)
        await feed.handle_message(
            {
                "type": "subscribed/order_book",
                "channel": "order_book@tier2/120",
                "order_book": {
                    "bids": [{"price": "1", "size": "2"}],
                    "asks": [{"price": "3", "size": "4"}],
                },
            }
        )
        self.assertTrue(feed.has_book(120))

    async def test_snapshot_stored_when_current_matches(self) -> None:
        feed = OrderBookFeed(lambda _msg: None)
        feed.set_current_market(120)
        await feed.handle_message(_SNAP)
        self.assertTrue(feed.has_book(120))
        payload = feed.order_book_payload(120)
        assert payload is not None
        self.assertEqual(payload["bids"][0]["price"], "1")
        self.assertEqual(payload["asks"][0]["price"], "3")

    async def test_pinned_snapshot_stored_when_not_current(self) -> None:
        emitted: list[dict] = []
        feed = OrderBookFeed(emitted.append)
        feed.set_current_market(1)
        feed.pin(120)
        await feed.handle_message(_SNAP)
        self.assertTrue(feed.has_book(120))
        self.assertTrue(feed.is_synced(120))
        self.assertFalse(any(m.get("type") == "book_sync" for m in emitted))

    async def test_flush_broadcasts_only_current_market(self) -> None:
        emitted: list[dict] = []
        feed = OrderBookFeed(emitted.append)
        feed.set_current_market(1)
        feed.pin(120)
        await feed.handle_message(_SNAP)
        snap1 = {
            "type": "subscribed/order_book",
            "channel": "order_book:1",
            "order_book": {"bids": [{"price": "9", "size": "1"}], "asks": [{"price": "10", "size": "1"}]},
        }
        await feed.handle_message(snap1)
        await asyncio.sleep(0.12)
        books = [m for m in emitted if m.get("type") == "order_book_snapshot"]
        self.assertTrue(any(m.get("market_index") == 1 for m in books))
        self.assertFalse(any(m.get("market_index") == 120 for m in books))

    async def test_payload_truncates_stored_depth(self) -> None:
        feed = OrderBookFeed(lambda _msg: None)
        feed.set_current_market(120)
        bids = [{"price": str(1000 - i), "size": "1"} for i in range(300)]
        asks = [{"price": str(2000 + i), "size": "1"} for i in range(300)]
        await feed.handle_message(
            {
                "type": "subscribed/order_book",
                "channel": "order_book:120",
                "order_book": {"bids": bids, "asks": asks, "nonce": 7},
            }
        )
        stored = feed._order_books[120]
        self.assertEqual(len(stored.bids), 300)
        self.assertEqual(len(stored.asks), 300)
        payload = feed.order_book_payload(120)
        assert payload is not None
        self.assertEqual(len(payload["bids"]), 250)
        self.assertEqual(len(payload["asks"]), 250)
        self.assertEqual(payload["bids"][0]["price"], "1000")

    @expects_logs()
    async def test_nonce_gap_drops_deltas_until_snapshot(self) -> None:
        resub: list[int] = []
        feed = OrderBookFeed(lambda _msg: None, resubscribe=resub.append)
        feed.set_current_market(120)
        await feed.handle_message(
            {
                "type": "subscribed/order_book",
                "channel": "order_book:120",
                "order_book": {
                    "bids": [{"price": "1", "size": "2"}],
                    "asks": [{"price": "3", "size": "4"}],
                    "nonce": 10,
                },
            }
        )
        self.assertEqual(feed.best_bid_ask(120), ("1", "3"))
        await feed.handle_message(
            {
                "type": "update/order_book",
                "channel": "order_book:120",
                "order_book": {
                    "bids": [{"price": "9", "size": "1"}],
                    "asks": [],
                    "nonce": 40,
                    "begin_nonce": 1,
                },
            }
        )
        self.assertEqual(resub, [120])
        self.assertFalse(feed.has_book(120))
        self.assertFalse(feed.is_synced(120))
        self.assertEqual(feed.best_bid_ask(120), (None, None))
        await feed.handle_message(
            {
                "type": "update/order_book",
                "channel": "order_book:120",
                "order_book": {
                    "bids": [{"price": "8", "size": "1"}],
                    "asks": [{"price": "9", "size": "1"}],
                    "nonce": 41,
                    "begin_nonce": 40,
                },
            }
        )
        self.assertFalse(feed.has_book(120))
        await feed.handle_message(
            {
                "type": "subscribed/order_book",
                "channel": "order_book:120",
                "order_book": {
                    "bids": [{"price": "5", "size": "1"}],
                    "asks": [{"price": "6", "size": "1"}],
                    "nonce": 80,
                },
            }
        )
        self.assertTrue(feed.is_synced(120))
        self.assertEqual(feed.best_bid_ask(120), ("5", "6"))

    async def test_invalidate_hides_touch_until_snapshot(self) -> None:
        feed = OrderBookFeed(lambda _msg: None)
        feed.set_current_market(120)
        await feed.handle_message(_SNAP)
        feed.invalidate(120)
        self.assertTrue(feed.has_book(120))
        self.assertFalse(feed.is_synced(120))
        self.assertEqual(feed.best_bid_ask(120), (None, None))

    async def test_same_market_activate_enables_book(self) -> None:
        gw = LighterGateway.__new__(LighterGateway)
        gw._lock = asyncio.Lock()
        gw._current_market_index = 120
        gw._ws = None
        gw._books = OrderBookFeed(lambda _msg: None)
        gw._prune_trade_buffers = lambda keep=None: None
        gw.broadcast = lambda message: None
        await gw.set_active_market(120)
        await gw._books.handle_message(_SNAP)
        self.assertTrue(gw._books.has_book(120))


class TestResolveSubscribeMarket(unittest.TestCase):
    def _gw(self) -> LighterGateway:
        gw = LighterGateway.__new__(LighterGateway)
        lit_perp = MarketMeta(120, "LIT", 5, 2, 3.5, 10.0, market_type="perp")
        lit_spot = MarketMeta(204, "LIT", 5, 2, 3.5, 10.0, market_type="spot")
        eth = MarketMeta(0, "ETH", 2, 4, 0.001, 10.0, market_type="perp")
        gw._markets = {120: lit_perp, 204: lit_spot, 0: eth}
        gw._perp_by_symbol = {"LIT": 120, "ETH": 0}
        gw._symbol_to_index = {"LIT": 120, "ETH": 0}
        gw._spot_by_symbol = {"LIT": 204}
        return gw

    def test_stale_index_for_other_symbol_is_ignored(self) -> None:
        self.assertEqual(self._gw().resolve_subscribe_market("LIT", 0), 120)

    def test_spot_index_maps_to_perp_for_desk(self) -> None:
        self.assertEqual(self._gw().resolve_subscribe_market("LIT", 204), 120)


if __name__ == "__main__":
    unittest.main()
