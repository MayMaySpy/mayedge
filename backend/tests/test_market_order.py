from __future__ import annotations

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock, patch

from mayedge.config import settings
from mayedge.lighter.account import AccountService
from mayedge.lighter.errors import VenueBlocked, venue_client_error
from mayedge.lighter.models import MarketMeta, parse_to_int
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


def _sky() -> MarketMeta:
    return MarketMeta(
        market_index=79,
        symbol="SKY",
        price_decimals=6,
        size_decimals=0,
        min_base_amount=100,
        min_quote_amount=10,
    )


class MakerMinTests(TestCase):
    def test_sky_110_clears_ten_dollar_min(self) -> None:
        meta = _sky()
        OrderService()._check_maker_size(
            meta, parse_to_int("110", 0), parse_to_int("0.094", 6)
        )

    def test_sky_106_asks_for_107(self) -> None:
        meta = _sky()
        with self.assertRaises(ValueError) as ctx:
            OrderService()._check_maker_size(
                meta, parse_to_int("106", 0), parse_to_int("0.094", 6)
            )
        self.assertEqual(str(ctx.exception), "Min 107 SKY (or $10)")


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
    def tearDown(self) -> None:
        from mayedge.lighter.budget import budget

        budget.reset()
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

    async def test_reduce_only_skips_notional_cap(self) -> None:
        svc = OrderService()
        svc._signer = MagicMock()
        svc._signer.create_market_order = AsyncMock(return_value=(None, "0xabc", None))
        svc._next_client_order_index = MagicMock(return_value=1_000_000_001)

        with (
            patch.object(settings, "max_order_notional", 100.0),
            patch.object(svc, "_market_meta", return_value=_eth()),
            patch(
                "mayedge.lighter.orders.gateway.best_bid_ask",
                return_value=("100", "100.10"),
            ),
        ):
            out = await svc.create_market_order(1, "sell", "1000", slippage=0.01, reduce_only=True)

        self.assertEqual(out["tx_hash"], "0xabc")

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


class OrderCapRejectTests(IsolatedAsyncioTestCase):
    def _limit_signer(self) -> MagicMock:
        signer = MagicMock()
        signer.ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL = 0
        signer.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME = 1
        signer.ORDER_TIME_IN_FORCE_POST_ONLY = 2
        signer.ORDER_TYPE_LIMIT = 0
        signer.DEFAULT_28_DAY_ORDER_EXPIRY = 0
        return signer

    async def test_limit_account_cap_raises(self) -> None:
        svc = OrderService()
        svc._signer = self._limit_signer()
        resp = SimpleNamespace(code=21717, message="max orders per account")
        svc._signer.create_order = AsyncMock(return_value=(None, resp, None))
        svc._next_client_order_index = MagicMock(return_value=1_000_000_001)

        with (
            patch.object(svc, "_market_meta", return_value=_eth()),
            self.assertRaises(ValueError) as ctx,
        ):
            await svc.create_limit_order(1, "buy", "1", "100")
        self.assertEqual(str(ctx.exception), "Account order cap reached")

    async def test_market_per_market_cap_raises(self) -> None:
        svc = OrderService()
        svc._signer = MagicMock()
        resp = SimpleNamespace(code=21718, message="max orders per market")
        svc._signer.create_market_order = AsyncMock(return_value=(None, resp, None))
        svc._next_client_order_index = MagicMock(return_value=1_000_000_001)

        with (
            patch.object(svc, "_market_meta", return_value=_eth()),
            patch(
                "mayedge.lighter.orders.gateway.best_bid_ask",
                return_value=("100", "100.10"),
            ),
            self.assertRaises(ValueError) as ctx,
        ):
            await svc.create_market_order(1, "buy", "1")
        self.assertEqual(str(ctx.exception), "Per-market order cap reached")


class AccountRestCooldownTests(IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        from mayedge.lighter.budget import budget

        budget.reset()

    async def test_summary_raises_while_cooling(self) -> None:
        from mayedge.lighter.budget import budget

        svc = AccountService()
        budget.note_blocked()
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

    def test_local_refusal_does_not_start_cooldown(self) -> None:
        from mayedge.lighter.budget import CAP, budget

        budget.reset()
        for _ in range(CAP):
            self.assertTrue(budget.try_acquire(lane="critical"))
        self.assertFalse(budget.try_acquire(lane="critical"))
        self.assertFalse(budget.cooling())
