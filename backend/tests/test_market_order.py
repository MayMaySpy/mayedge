from __future__ import annotations

from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock, patch

from mayedge.lighter.account import AccountService
from mayedge.lighter.errors import VenueBlocked, venue_client_error
from mayedge.lighter.models import MarketMeta
from mayedge.lighter.orders import OrderService

WAF_HTML = (
    "(405) Reason: Not Allowed HTTP response headers: "
    "<CIMultiDictProxy('x-amzn-waf-action': 'captcha')> "
    "HTTP response body: <title>Human Verification</title>"
)


def _eth() -> MarketMeta:
    return MarketMeta(
        market_index=1,
        symbol="ETH",
        price_decimals=2,
        size_decimals=1,
        min_base_amount=0.1,
        min_quote_amount=0.0,
        last_trade_price=100.0,
        mark_price=100.0,
    )


class VenueClientErrorTests(TestCase):
    def test_waf_captcha_html_is_429(self) -> None:
        mapped = venue_client_error(WAF_HTML)
        self.assertIsNotNone(mapped)
        assert mapped is not None
        self.assertEqual(mapped[0], 429)
        self.assertIn("WAF", mapped[1])

    def test_plain_error_is_none(self) -> None:
        self.assertIsNone(venue_client_error("invalid nonce"))


class MarketOrderLocalBookTests(IsolatedAsyncioTestCase):
    async def test_buy_uses_ask_and_does_not_rest_fetch_book(self) -> None:
        svc = OrderService()
        svc._signer = MagicMock()
        svc._signer.create_market_order = AsyncMock(return_value=(None, "0xabc", None))
        svc._signer.create_market_order_if_slippage = AsyncMock()
        svc._next_client_order_index = MagicMock(return_value=1_000_000_001)

        with (
            patch.object(svc, "_market_meta", return_value=_eth()),
            patch(
                "mayedge.lighter.orders.gateway.best_bid_ask",
                return_value=("100", "100.10"),
            ),
        ):
            out = await svc.create_market_order(1, "buy", "1", slippage=0.01)

        self.assertEqual(out["tx_hash"], "0xabc")
        call = svc._signer.create_market_order.await_args.kwargs
        self.assertEqual(call["avg_execution_price"], 10110)
        self.assertEqual(call["is_ask"], False)
        svc._signer.create_market_order_if_slippage.assert_not_called()

    async def test_sell_uses_bid(self) -> None:
        svc = OrderService()
        svc._signer = MagicMock()
        svc._signer.create_market_order = AsyncMock(return_value=(None, "0xabc", None))
        svc._next_client_order_index = MagicMock(return_value=1_000_000_001)

        with (
            patch.object(svc, "_market_meta", return_value=_eth()),
            patch(
                "mayedge.lighter.orders.gateway.best_bid_ask",
                return_value=("100", "100.10"),
            ),
        ):
            await svc.create_market_order(1, "sell", "1", slippage=0.01)

        call = svc._signer.create_market_order.await_args.kwargs
        self.assertEqual(call["avg_execution_price"], 9900)
        self.assertEqual(call["is_ask"], True)

    async def test_waf_on_send_is_venue_blocked(self) -> None:
        svc = OrderService()
        svc._signer = MagicMock()
        svc._signer.create_market_order = AsyncMock(return_value=(None, None, WAF_HTML))
        svc._next_client_order_index = MagicMock(return_value=1_000_000_001)

        with (
            patch.object(svc, "_market_meta", return_value=_eth()),
            patch(
                "mayedge.lighter.orders.gateway.best_bid_ask",
                return_value=("100", "100.10"),
            ),
            self.assertRaises(VenueBlocked) as ctx,
        ):
            await svc.create_market_order(1, "buy", "1")
        self.assertEqual(ctx.exception.status, 429)


class AccountRestCooldownTests(IsolatedAsyncioTestCase):
    async def test_summary_raises_while_cooling(self) -> None:
        import time

        svc = AccountService()
        svc._rest_cool_until = time.monotonic() + 60
        with (
            patch("mayedge.lighter.account.settings") as settings,
            patch("mayedge.lighter.account.lighter.AccountApi") as api,
        ):
            settings.lighter_account_index = 1
            with self.assertRaises(VenueBlocked):
                await svc.fetch_account_summary()
            api.assert_not_called()

    def test_waf_sets_cooldown(self) -> None:
        svc = AccountService()
        self.assertTrue(svc._note_rest_error(Exception(WAF_HTML), "test"))
        self.assertTrue(svc._rest_cooling())
        svc.kick_refresh()
        self.assertIsNone(svc._refresh_task)

    def test_token_bucket_blocks_before_venue_429(self) -> None:
        from mayedge.lighter import account as account_mod

        svc = AccountService()
        for _ in range(account_mod._REST_BUDGET):
            svc._take_rest()
        with self.assertRaises(VenueBlocked) as ctx:
            svc._take_rest()
        self.assertEqual(ctx.exception.status, 429)
        self.assertTrue(svc._rest_cooling())
