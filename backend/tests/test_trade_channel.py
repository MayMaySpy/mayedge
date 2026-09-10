"""Trade-channel parsing: paced subs must not leak onto the selected pair."""

from __future__ import annotations

import unittest

from mayedge.lighter.channels import parse_channel_market, split_ws_type
from mayedge.lighter.gateway import LighterGateway
from mayedge.lighter.liquidations import LiquidationFeed
from mayedge.lighter.market_ws import handle_candle, handle_trades, handle_ws_message
from mayedge.lighter.models import Trade


class TestParseChannelMarket(unittest.TestCase):
    def test_trade_forms(self) -> None:
        self.assertEqual(parse_channel_market("trade:120", "trade"), 120)
        self.assertEqual(parse_channel_market("trade/0", "trade"), 0)
        self.assertEqual(parse_channel_market(77, "trade"), 77)

    def test_official_fe_and_tier_channels(self) -> None:
        self.assertEqual(parse_channel_market("trade_fe:120", "trade"), 120)
        self.assertEqual(parse_channel_market("trade_fe/0", "trade"), 0)
        self.assertEqual(parse_channel_market("order_book@tier2/120", "order_book"), 120)
        self.assertIsNone(parse_channel_market("order_book@tier2/120", "trade"))

    def test_candle_strips_resolution(self) -> None:
        self.assertEqual(parse_channel_market("candle:123/1m", "candle"), 123)
        self.assertEqual(parse_channel_market("candle/123/1m", "candle"), 123)

    def test_unparsed_is_none_not_guessed(self) -> None:
        self.assertIsNone(parse_channel_market("trade", "trade"))
        self.assertIsNone(parse_channel_market("", "trade"))
        self.assertIsNone(parse_channel_market(None, "trade"))
        self.assertIsNone(parse_channel_market("order_book:5", "trade"))


class TestSplitWsType(unittest.TestCase):
    def test_strips_fe_suffix(self) -> None:
        self.assertEqual(split_ws_type("subscribed/trade_fe"), ("subscribed", "trade"))
        self.assertEqual(split_ws_type("update/trade_fe"), ("update", "trade"))
        self.assertEqual(
            split_ws_type("update/account_all_positions_fe"),
            ("update", "account_all_positions"),
        )

    def test_plain_kinds(self) -> None:
        self.assertEqual(split_ws_type("subscribed/order_book"), ("subscribed", "order_book"))
        self.assertEqual(split_ws_type("update/candle"), ("update", "candle"))


class TestTradeSnapshotIsolation(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        gw = LighterGateway.__new__(LighterGateway)
        gw._current_market_index = 120
        gw._recent_trades = {120: [Trade(price="1", size="1", side="buy", timestamp=1)]}
        gw._candles_1s = {}
        gw._max_1s = 3600
        gw._subscribers = []
        gw._markets = {}
        gw._liqs = LiquidationFeed(lambda _msg: None, persist=False)
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
            snapshot=True,
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
            snapshot=True,
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
            snapshot=True,
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
            snapshot=True,
        )
        self.assertEqual(self.gw._recent_trades[120][0].price, "42")
        self.assertTrue(any(m.get("type") == "trades" for m in self.out))

    async def test_snapshot_ingests_liquidation_trades(self) -> None:
        await handle_trades(
            self.gw,
            {
                "channel": "trade_fe:1",
                "trades": None,
                "liquidation_trades": [
                    {
                        "trade_id": 99,
                        "price": "10",
                        "size": "2",
                        "usd_amount": "20",
                        "timestamp": 1_700_000_000_000,
                        "type": "liquidation",
                    }
                ],
            },
            snapshot=True,
        )
        rows = self.gw._liqs.recent()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["trade_id"], "99")

    async def test_trade_fe_update_routes_to_tape(self) -> None:
        await handle_ws_message(
            self.gw,
            {
                "type": "update/trade_fe",
                "channel": "trade_fe/120",
                "trades": [
                    {
                        "price": "7",
                        "size": "1",
                        "timestamp": 9,
                        "is_maker_ask": True,
                    }
                ],
            },
        )
        self.assertEqual(self.gw._recent_trades[120][0].price, "7")
        self.assertTrue(any(m.get("type") == "trades" for m in self.out))


class TestHandleCandle(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.out: list[dict] = []
        gw = LighterGateway.__new__(LighterGateway)
        gw._current_market_index = 1
        gw.broadcast = lambda message: self.out.append(message)
        self.gw = gw

    async def test_subscribed_dump_replaces_even_when_short(self) -> None:
        await handle_candle(
            self.gw,
            {
                "type": "subscribed/candle",
                "channel": "candle/1/1m",
                "candles": [
                    {"t": 1_700_000_000, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1},
                    {"t": 1_700_000_060, "o": 2, "h": 2, "l": 2, "c": 2, "v": 1},
                ],
            },
        )
        self.assertEqual(len(self.out), 1)
        self.assertEqual(self.out[0]["type"], "candles")
        self.assertEqual(len(self.out[0]["candles"]), 2)

    async def test_history_dump_is_one_capped_snapshot(self) -> None:
        await handle_candle(
            self.gw,
            {
                "type": "subscribed/candle",
                "channel": "candle/1/1m",
                "candles": [
                    {"t": 1_700_000_000, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1},
                    {"t": 1_700_000_060, "o": 2, "h": 2, "l": 2, "c": 2, "v": 1},
                    {"t": 1_700_000_120, "o": 3, "h": 3, "l": 3, "c": 3, "v": 1},
                ],
            },
        )
        self.assertEqual(len(self.out), 1)
        self.assertEqual(self.out[0]["type"], "candles")
        self.assertEqual(len(self.out[0]["candles"]), 3)

    async def test_rollover_upserts_closed_and_new_bar(self) -> None:
        await handle_candle(
            self.gw,
            {
                "type": "update/candle",
                "channel": "candle/1/1m",
                "candles": [
                    {"t": 1_700_000_040, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1},
                    {"t": 1_700_000_100, "o": 2, "h": 2, "l": 2, "c": 2, "v": 1},
                ],
            },
        )
        self.assertEqual(len(self.out), 1)
        self.assertEqual(self.out[0]["type"], "candle")
        self.assertEqual(len(self.out[0]["candles"]), 2)
        self.assertEqual(self.out[0]["candles"][0]["time"], 1_700_000_040)
        self.assertEqual(self.out[0]["candles"][1]["time"], 1_700_000_100)

    async def test_update_is_one_minute_bucket(self) -> None:
        await handle_candle(
            self.gw,
            {
                "type": "update/candle",
                "channel": "candle/1/1m",
                "candlestick": {
                    "t": 1_700_000_123_000,
                    "o": 1,
                    "h": 2,
                    "l": 0.5,
                    "c": 1.5,
                    "v": 3,
                },
            },
        )
        self.assertEqual(len(self.out), 1)
        self.assertEqual(self.out[0]["type"], "candle")
        self.assertEqual(self.out[0]["candle"]["time"] % 60, 0)

    async def test_unparsed_channel_does_not_fall_back_to_current(self) -> None:
        await handle_candle(
            self.gw,
            {
                "type": "update/candle",
                "channel": "candle",
                "candles": [{"t": 1_700_000_000, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}],
            },
        )
        self.assertEqual(self.out, [])


if __name__ == "__main__":
    unittest.main()
