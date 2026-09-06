from __future__ import annotations

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from mayedge.lighter.models import MarketMeta
from mayedge.lighter.orders import OrderService


class TwapSlippageTests(IsolatedAsyncioTestCase):
    async def test_buy_worst_price_uses_slippage(self) -> None:
        svc = OrderService()
        svc._signer = MagicMock()
        svc._signer.ORDER_TYPE_TWAP = 2
        svc._signer.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME = 1
        svc._signer.DEFAULT_28_DAY_ORDER_EXPIRY = 0
        svc._signer.create_order = AsyncMock(return_value=(None, MagicMock(tx_hash="0x"), None))
        svc._next_client_order_index = MagicMock(return_value=1_000_000_001)

        meta = MarketMeta(
            market_index=1,
            symbol="ETH",
            price_decimals=2,
            size_decimals=1,
            min_base_amount=0.1,
            min_quote_amount=0.0,
            last_trade_price=100.0,
            mark_price=100.0,
        )

        with (
            patch.object(svc, "_market_meta", return_value=meta),
            patch(
                "mayedge.lighter.orders.gateway.best_bid_ask",
                return_value=("100", "100.10"),
            ),
        ):
            await svc.create_twap_order(
                market_index=1,
                side="buy",
                size="1",
                duration_seconds=900,
                max_slippage=0.01,
            )

        call = svc._signer.create_order.await_args.kwargs
        self.assertEqual(call["price"], 10105)

    async def test_sell_worst_price_uses_slippage(self) -> None:
        svc = OrderService()
        svc._signer = MagicMock()
        svc._signer.ORDER_TYPE_TWAP = 2
        svc._signer.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME = 1
        svc._signer.DEFAULT_28_DAY_ORDER_EXPIRY = 0
        svc._signer.create_order = AsyncMock(return_value=(None, MagicMock(tx_hash="0x"), None))
        svc._next_client_order_index = MagicMock(return_value=1_000_000_001)

        meta = MarketMeta(
            market_index=1,
            symbol="ETH",
            price_decimals=2,
            size_decimals=1,
            min_base_amount=0.1,
            min_quote_amount=0.0,
            last_trade_price=100.0,
            mark_price=100.0,
        )

        with (
            patch.object(svc, "_market_meta", return_value=meta),
            patch(
                "mayedge.lighter.orders.gateway.best_bid_ask",
                return_value=("100", "100.10"),
            ),
        ):
            await svc.create_twap_order(
                market_index=1,
                side="sell",
                size="1",
                duration_seconds=900,
                max_slippage=0.01,
            )

        call = svc._signer.create_order.await_args.kwargs
        self.assertEqual(call["price"], 9904)
