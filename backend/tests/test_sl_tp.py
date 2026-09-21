from __future__ import annotations

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from mayedge.lighter.models import MarketMeta
from mayedge.lighter.orders import OrderService


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


def _signer() -> MagicMock:
    signer = MagicMock()
    signer.ORDER_TYPE_STOP_LOSS = 2
    signer.ORDER_TYPE_STOP_LOSS_LIMIT = 3
    signer.ORDER_TYPE_TAKE_PROFIT = 4
    signer.ORDER_TYPE_TAKE_PROFIT_LIMIT = 5
    signer.ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL = 0
    signer.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME = 1
    signer.DEFAULT_28_DAY_ORDER_EXPIRY = -1
    signer.GROUPING_TYPE_ONE_CANCELS_THE_OTHER = 2
    ok = (None, SimpleNamespace(code=200, tx_hash="0xsltp"), None)
    signer.create_sl_order = AsyncMock(return_value=ok)
    signer.create_sl_limit_order = AsyncMock(return_value=ok)
    signer.create_tp_order = AsyncMock(return_value=ok)
    signer.create_tp_limit_order = AsyncMock(return_value=ok)
    signer.create_grouped_orders = AsyncMock(return_value=ok)
    return signer


class StopTakeOrderTests(IsolatedAsyncioTestCase):
    def _svc(self) -> OrderService:
        svc = OrderService()
        svc._signer = _signer()
        svc._next_client_order_index = MagicMock(side_effect=[1_000_000_001, 1_000_000_002])
        return svc

    async def test_market_stop_prices_from_trigger_not_book(self) -> None:
        svc = self._svc()
        with patch.object(svc, "_market_meta", return_value=_eth()):
            out = await svc.create_sl_tp(
                1,
                "sell",
                "1",
                sl={"kind": "market", "trigger": "90"},
                slippage=0.01,
            )
        self.assertEqual(out["tx_hash"], "0xsltp")
        signer = svc._signer
        assert isinstance(signer, MagicMock)
        call = signer.create_sl_order.await_args.kwargs
        self.assertEqual(call["trigger_price"], 9000)
        self.assertEqual(call["price"], 8910)
        self.assertEqual(call["base_amount"], 10)
        self.assertTrue(call["reduce_only"])
        self.assertTrue(call["is_ask"])
        signer.create_grouped_orders.assert_not_called()

    async def test_full_close_sends_zero_size(self) -> None:
        svc = self._svc()
        with patch.object(svc, "_market_meta", return_value=_eth()):
            await svc.create_sl_tp(
                1,
                "sell",
                "0",
                sl={"kind": "market", "trigger": "90"},
            )
        signer = svc._signer
        assert isinstance(signer, MagicMock)
        self.assertEqual(signer.create_sl_order.await_args.kwargs["base_amount"], 0)

    async def test_both_legs_are_oco(self) -> None:
        svc = self._svc()
        with patch.object(svc, "_market_meta", return_value=_eth()):
            await svc.create_sl_tp(
                1,
                "sell",
                "0",
                sl={"kind": "market", "trigger": "90"},
                tp={"kind": "limit", "trigger": "120", "price": "119.5"},
            )
        signer = svc._signer
        assert isinstance(signer, MagicMock)
        signer.create_sl_order.assert_not_called()
        kw = signer.create_grouped_orders.await_args.kwargs
        self.assertEqual(kw["grouping_type"], 2)
        self.assertEqual(len(kw["orders"]), 2)
        sl, tp = kw["orders"]
        self.assertEqual(sl.Type, 2)
        self.assertEqual(sl.TriggerPrice, 9000)
        self.assertEqual(sl.BaseAmount, 0)
        self.assertEqual(sl.ReduceOnly, 1)
        self.assertEqual(tp.Type, 5)
        self.assertEqual(tp.TriggerPrice, 12000)
        self.assertEqual(tp.Price, 11950)

    async def test_rejects_empty_legs(self) -> None:
        svc = self._svc()
        with (
            patch.object(svc, "_market_meta", return_value=_eth()),
            self.assertRaises(ValueError) as ctx,
        ):
            await svc.create_sl_tp(1, "sell", "1")
        self.assertIn("stop or take profit", str(ctx.exception).lower())

    async def test_limit_requires_price(self) -> None:
        svc = self._svc()
        with (
            patch.object(svc, "_market_meta", return_value=_eth()),
            self.assertRaises(ValueError) as ctx,
        ):
            await svc.create_sl_tp(
                1,
                "sell",
                "1",
                sl={"kind": "limit", "trigger": "90"},
            )
        self.assertIn("limit price", str(ctx.exception).lower())

    async def test_stop_on_wrong_side_of_mark_rejected(self) -> None:
        svc = self._svc()
        with (
            patch.object(svc, "_market_meta", return_value=_eth()),
            self.assertRaises(ValueError) as ctx,
        ):
            await svc.create_sl_tp(
                1,
                "sell",
                "1",
                sl={"kind": "market", "trigger": "110"},
            )
        self.assertIn("wrong side", str(ctx.exception).lower())
