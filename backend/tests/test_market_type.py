"""Markets the desk does not understand stay out. High indexes pass through."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, cast
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock, patch

from mayedge.lighter.gateway import LighterGateway
from mayedge.lighter.models import normalize_market_type
from mayedge.lighter.parse import merge_positions


def _book(symbol: str, market_id: int, market_type: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        symbol=symbol,
        market_id=market_id,
        status="active",
        price_decimals=2,
        size_decimals=4,
        min_base_amount="0.001",
        min_quote_amount="10",
        market_type=market_type,
    )


class MarketTypeTests(TestCase):
    def test_missing_and_empty_stay_perp(self) -> None:
        self.assertEqual(normalize_market_type(None), "perp")
        self.assertEqual(normalize_market_type(""), "perp")
        self.assertEqual(normalize_market_type("   "), "perp")

    def test_known_perp_and_spot(self) -> None:
        self.assertEqual(normalize_market_type("perp"), "perp")
        self.assertEqual(normalize_market_type("Perp"), "perp")
        self.assertEqual(normalize_market_type("spot"), "spot")
        self.assertEqual(normalize_market_type("SPOT"), "spot")

    def test_binary_options_and_unknown_are_other(self) -> None:
        self.assertEqual(normalize_market_type("binary_options"), "other")
        self.assertEqual(normalize_market_type("mystery"), "other")


class LoadMarketsTests(IsolatedAsyncioTestCase):
    async def test_a_binary_row_stays_out_of_the_desk(self) -> None:
        rows = [
            _book("BTC", 1, "perp"),
            _book("ETH", 2048, "spot"),
            _book("STONK-UP", 9001, "binary_options"),
            _book("???", 9002, "mystery"),
        ]
        order_api = MagicMock()
        order_api.order_book_details = AsyncMock(
            return_value=SimpleNamespace(order_book_details=rows, spot_order_book_details=[])
        )
        gw = LighterGateway()
        gw._client = cast(Any, object())
        with (
            patch("mayedge.lighter.gateway.lighter.OrderApi", return_value=order_api),
            self.assertLogs("mayedge.lighter.gateway", level=logging.INFO) as logs,
        ):
            await gw._load_markets()
        symbols = {meta.symbol for meta in gw.list_markets()}
        self.assertEqual(symbols, {"BTC", "ETH"})
        self.assertNotIn(9001, gw._markets)
        self.assertIsNone(gw.get_market_by_index(9001))
        funding = [m.symbol for m in gw._markets.values() if m.is_perp]
        self.assertEqual(funding, ["BTC"])
        self.assertNotIn("STONK-UP", str(gw.scan_activity()))
        self.assertNotIn("STONK-UP", str(gw.recent_alerts()))
        joined = " ".join(logs.output)
        self.assertIn("STONK-UP (binary_options)", joined)
        self.assertIn("??? (mystery)", joined)
        self.assertEqual(sum("skipped markets" in line for line in logs.output), 1)


class UnknownPositionTests(TestCase):
    def test_a_position_on_an_unknown_market_publishes(self) -> None:
        positions = merge_positions(
            [],
            [
                {
                    "market_id": 99999,
                    "position": "1.5",
                    "symbol": "BOOP",
                    "sign": 1,
                    "unrealized_pnl": "3",
                }
            ],
            snapshot=True,
        )
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0].market_index, 99999)
        self.assertEqual(positions[0].symbol, "BOOP")
        self.assertEqual(positions[0].unrealized_pnl, "3")
