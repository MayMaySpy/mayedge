"""Trade-channel parsing: paced subs must not leak onto the selected pair."""

from __future__ import annotations

import unittest

from mayedge.lighter.channels import parse_channel_market
from mayedge.lighter.gateway import LighterGateway
from mayedge.lighter.liquidations import LiquidationFeed
from mayedge.lighter.market_ws import handle_trades
from mayedge.lighter.models import Trade


class TestParseChannelMarket(unittest.TestCase):
    def test_trade_forms(self) -> None:
        self.assertEqual(parse_channel_market("trade:120", "trade"), 120)
        self.assertEqual(parse_channel_market("trade/0", "trade"), 0)
        self.assertEqual(parse_channel_market(77, "trade"), 77)

    def test_candle_strips_resolution(self) -> None:
        self.assertEqual(parse_channel_market("candle:123/1m", "candle"), 123)
        self.assertEqual(parse_channel_market("candle/123/1m", "candle"), 123)

    def test_unparsed_is_none_not_guessed(self) -> None:
        self.assertIsNone(parse_channel_market("trade", "trade"))
        self.assertIsNone(parse_channel_market("", "trade"))
        self.assertIsNone(parse_channel_market(None, "trade"))
        self.assertIsNone(parse_channel_market("order_book:5", "trade"))


class TestTradeSnapshotIsolation(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        gw = LighterGateway.__new__(LighterGateway)
        gw._current_market_index = 120
        gw._recent_trades = {120: [Trade(price="1", size="1", side="buy", timestamp=1)]}
        gw._candles_1s = {}
        gw._max_1s = 3600
        gw._subscribers = []
        gw._markets = {}
        gw._liqs = LiquidationFeed(lambda _msg: None)
        self.out: list[dict] = []
        gw.subscribe(self.out.append)
        self.gw = gw

    async def test_other_market_snapshot_does_not_touch_tape(self) -> None:
        await handle_trades(
            self.gw,
            {
                "channel": "trade:1",
                "trades": [{"price": "999", "size": "1", "timestamp": 2}],
            },
            live=False,
        )
        self.assertEqual(self.gw._recent_trades[120][0].price, "1")
        self.assertEqual(self.out, [])

    async def test_unparsed_channel_does_not_fall_back_to_current(self) -> None:
        await handle_trades(
            self.gw,
            {
                "channel": "trade",
                "trades": [{"price": "999", "size": "1", "timestamp": 2}],
            },
            live=False,
        )
        self.assertEqual(self.gw._recent_trades[120][0].price, "1")
        self.assertEqual(self.out, [])

    async def test_snapshot_skipped_when_tape_already_seeded(self) -> None:
        await handle_trades(
            self.gw,
            {
                "channel": "trade:120",
                "trades": [{"price": "999", "size": "1", "timestamp": 2}],
            },
            live=False,
        )
        self.assertEqual(self.gw._recent_trades[120][0].price, "1")
        self.assertEqual(self.out, [])

    async def test_empty_tape_snapshot_seeds_active_market(self) -> None:
        self.gw._recent_trades = {}
        await handle_trades(
            self.gw,
            {
                "channel": "trade:120",
                "trades": [{"price": "42", "size": "1", "timestamp": 9, "is_maker_ask": False}],
            },
            live=False,
        )
        self.assertEqual(self.gw._recent_trades[120][0].price, "42")
        self.assertTrue(any(m.get("type") == "trades" for m in self.out))


if __name__ == "__main__":
    unittest.main()
