from __future__ import annotations

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock, patch

from expect_logs import expects_logs

from mayedge.algos.chase.util import _is_would_cross
from mayedge.config import settings
from mayedge.lighter.account import AccountService
from mayedge.lighter.errors import (
    RATE_MSG,
    WAF_MSG,
    VenueBlocked,
    has_code,
    http_block,
    venue_client_error,
)
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
        OrderService()._check_maker_size(meta, parse_to_int("110", 0), parse_to_int("0.094", 6))

    def test_sky_106_asks_for_107(self) -> None:
        meta = _sky()
        with self.assertRaises(ValueError) as ctx:
            OrderService()._check_maker_size(meta, parse_to_int("106", 0), parse_to_int("0.094", 6))
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

    def test_status_and_venue_codes_are_rate_limits(self) -> None:
        for text in (
            "(429)\nReason: Too Many Requests",
            'HTTP response body: {"code":23000,"message":"Too Many Requests!"}',
            "code=23000 message='ratelimit'",
            "Order failed (429)",
        ):
            self.assertEqual(venue_client_error(text), (429, RATE_MSG), text)

    def test_digits_inside_a_number_are_not_a_rate_limit(self) -> None:
        for text in (
            "order price 64290.5 is too far from mark",
            "order 281474976429001 not found",
            "invalid order base or quote amount (min 0.23000)",
            "funding change 0.00429 at 1759429200",
        ):
            self.assertIsNone(venue_client_error(text), text)

    def test_a_200_body_is_never_a_block(self) -> None:
        body = '{"code":200,"position_fundings":[{"timestamp":1759429200,"change":"0.429"}]}'
        self.assertIsNone(http_block(200, body))
        self.assertEqual(http_block(429, ""), (429, RATE_MSG))
        self.assertEqual(http_block(405, "<title>405 Not Allowed</title>"), (429, WAF_MSG))
        self.assertIsNone(http_block(400, '{"code":20001,"message":"invalid param 4290"}'))

    def test_code_checks_ignore_longer_numbers(self) -> None:
        self.assertTrue(has_code("code=21706 invalid order base or quote amount", "21706"))
        self.assertFalse(has_code("order 8000021706 rejected", "21706"))
        self.assertFalse(_is_would_cross(RuntimeError("order 82170 rejected at 121705.5")))
        self.assertTrue(_is_would_cross(RuntimeError("code=21702 would cross")))
        self.assertTrue(_is_would_cross(RuntimeError("rejected (21702)")))


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

    @expects_logs()
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


class NotionalCapPricingTests(IsolatedAsyncioTestCase):
    def _svc(self) -> OrderService:
        svc = OrderService()
        signer = MagicMock()
        signer.ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL = 0
        signer.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME = 1
        signer.ORDER_TIME_IN_FORCE_POST_ONLY = 2
        signer.ORDER_TYPE_LIMIT = 0
        signer.DEFAULT_28_DAY_ORDER_EXPIRY = 0
        ok = (None, SimpleNamespace(code=200, tx_hash="0xok"), None)
        signer.create_order = AsyncMock(return_value=ok)
        signer.modify_order = AsyncMock(return_value=ok)
        svc._signer = signer
        svc._next_client_order_index = MagicMock(return_value=1_000_000_001)
        return svc

    async def test_sell_priced_under_the_market_is_capped_at_the_market(self) -> None:
        svc = self._svc()
        with (
            patch.object(settings, "max_order_notional", 500.0),
            patch.object(svc, "_market_meta", return_value=_eth()),
            self.assertRaises(ValueError) as ctx,
        ):
            # 10 ETH at a typo'd $10 is $100 on paper and $1,000 at the $100 market.
            await svc.create_limit_order(1, "sell", "10", "10")
        self.assertIn("exceeds limit", str(ctx.exception))
        signer = svc._signer
        assert isinstance(signer, MagicMock)
        signer.create_order.assert_not_called()

    async def test_buy_resting_under_the_market_is_capped_at_its_limit(self) -> None:
        svc = self._svc()
        with (
            patch.object(settings, "max_order_notional", 500.0),
            patch.object(svc, "_market_meta", return_value=_eth()),
        ):
            out = await svc.create_limit_order(1, "buy", "10", "10")
        self.assertEqual(out["tx_hash"], "0xok")

    async def test_sell_above_the_market_is_capped_at_its_limit(self) -> None:
        svc = self._svc()
        with (
            patch.object(settings, "max_order_notional", 500.0),
            patch.object(svc, "_market_meta", return_value=_eth()),
            self.assertRaises(ValueError),
        ):
            await svc.create_limit_order(1, "sell", "4", "150")

    async def test_amending_a_sell_ticket_under_the_market_is_capped(self) -> None:
        from mayedge.lighter.models import OpenOrder

        svc = self._svc()
        live = OpenOrder(
            order_index=77,
            client_order_index=1_000_000_009,
            market_index=1,
            symbol="ETH",
            side="sell",
            price="120",
            size="10",
            remaining="10",
            order_type="limit",
            reduce_only=False,
        )
        with (
            patch.object(settings, "max_order_notional", 500.0),
            patch.object(svc, "_market_meta", return_value=_eth()),
            patch("mayedge.lighter.orders.account_service.find_open_order", return_value=live),
            self.assertRaises(ValueError) as ctx,
        ):
            await svc.amend_ticket(1, 77, "10")
        self.assertIn("exceeds limit", str(ctx.exception))


class TimeInForceTests(IsolatedAsyncioTestCase):
    async def test_unknown_time_in_force_is_refused_not_rested(self) -> None:
        svc = OrderService()
        svc._signer = MagicMock()
        svc._signer.create_order = AsyncMock()
        with (
            patch.object(svc, "_market_meta", return_value=_eth()),
            self.assertRaises(ValueError) as ctx,
        ):
            await svc.create_limit_order(1, "buy", "1", "100", time_in_force="ioc ")
        self.assertIn("time_in_force", str(ctx.exception))
        svc._signer.create_order.assert_not_called()

    def test_request_schema_refuses_an_unknown_time_in_force(self) -> None:
        from pydantic import ValidationError

        from mayedge.api.schemas import LimitOrderRequest

        base = {"market_index": 1, "side": "buy", "size": "1", "price": "100"}
        self.assertEqual(LimitOrderRequest(**base).time_in_force, "gtt")
        with self.assertRaises(ValidationError):
            LimitOrderRequest.model_validate({**base, "time_in_force": "gtc"})


class AccountRestCooldownTests(IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        from mayedge.lighter.budget import budget

        budget.reset()

    @expects_logs()
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

    @expects_logs()
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


class HighIndexTests(IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        from mayedge.lighter.budget import budget

        budget.reset()

    def _svc(self) -> OrderService:
        svc = OrderService()
        signer = MagicMock()
        signer.create_market_order = AsyncMock(return_value=(None, "0xabc", None))
        signer.create_order = AsyncMock(return_value=(None, "0xabc", None))
        signer.create_sl_order = AsyncMock(return_value=(None, "0xabc", None))
        signer.cancel_order = AsyncMock(
            return_value=(None, SimpleNamespace(code=200, tx_hash="0xabc"), None)
        )
        signer.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME = 1
        signer.ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL = 0
        signer.ORDER_TIME_IN_FORCE_POST_ONLY = 2
        signer.ORDER_TYPE_LIMIT = 0
        signer.ORDER_TYPE_STOP_LOSS = 2
        signer.DEFAULT_28_DAY_ORDER_EXPIRY = 0
        svc._signer = signer
        svc._next_client_order_index = MagicMock(return_value=1_000_000_001)
        return svc

    async def test_create_and_cancel_send_4099(self) -> None:
        svc = self._svc()
        signer = svc._signer
        self.assertIsInstance(signer, MagicMock)
        assert isinstance(signer, MagicMock)
        meta = _eth()
        with (
            patch.object(svc, "_market_meta", return_value=meta),
            patch("mayedge.lighter.orders.gateway.best_bid_ask", return_value=("100", "100.10")),
            patch("mayedge.lighter.orders.account_service.list_open_orders", return_value=[]),
        ):
            await svc.create_market_order(4099, "buy", "1", slippage=0.01)
            await svc.create_limit_order(4099, "buy", "1", "100")
            await svc.create_sl_tp(4099, "sell", "1", sl={"kind": "market", "trigger": "90"})
            await svc.cancel_order(4099, 7)
        self.assertEqual(signer.create_market_order.await_args.kwargs["market_index"], 4099)
        self.assertEqual(signer.create_order.await_args.kwargs["market_index"], 4099)
        self.assertEqual(signer.create_sl_order.await_args.kwargs["market_index"], 4099)
        self.assertEqual(signer.cancel_order.await_args.kwargs["market_index"], 4099)
