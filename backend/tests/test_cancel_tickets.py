from __future__ import annotations

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from mayedge.algos.chase.config import CHASE_COI_BASE
from mayedge.lighter.models import OpenOrder
from mayedge.lighter.orders import OrderService


def _order(**kw: object) -> OpenOrder:
    defaults: dict[str, object] = {
        "order_index": 42,
        "client_order_index": 1_000_000_001,
        "market_index": 1,
        "symbol": "ETH",
        "side": "buy",
        "price": "100.00",
        "size": "0.5",
        "remaining": "0.4",
        "order_type": "limit",
        "reduce_only": False,
    }
    defaults.update(kw)
    return OpenOrder(**defaults)  # type: ignore[arg-type]


class CancelTicketsTests(IsolatedAsyncioTestCase):
    async def test_cancels_buy_tickets_skips_sells_and_clips(self) -> None:
        svc = OrderService()
        svc._signer = MagicMock()
        svc._signer.cancel_order = AsyncMock(return_value=(None, "0xcan", None))
        rows = [
            _order(order_index=1, side="buy"),
            _order(order_index=2, side="sell", client_order_index=1_000_000_002),
            _order(
                order_index=3,
                side="buy",
                client_order_index=CHASE_COI_BASE + 3,
            ),
            _order(order_index=4, side="buy", client_order_index=1_000_000_004),
        ]

        with patch(
            "mayedge.lighter.orders.account_service.list_open_orders",
            return_value=rows,
        ):
            out = await svc.cancel_tickets("buy", None)

        self.assertEqual(out["cancelled"], 2)
        self.assertNotIn("error", out)
        called = [c.kwargs["order_index"] for c in svc._signer.cancel_order.await_args_list]
        self.assertEqual(called, [1, 4])
        for c in svc._signer.cancel_order.await_args_list:
            self.assertEqual(c.kwargs["market_index"], 1)

    async def test_market_index_limits_scope(self) -> None:
        svc = OrderService()
        svc._signer = MagicMock()
        svc._signer.cancel_order = AsyncMock(return_value=(None, "0xcan", None))
        rows = [
            _order(order_index=1, market_index=1, side="buy"),
            _order(order_index=2, market_index=2, side="buy", client_order_index=1_000_000_002),
        ]

        with patch(
            "mayedge.lighter.orders.account_service.list_open_orders",
            return_value=rows,
        ):
            scoped = await svc.cancel_tickets("buy", 1)
            all_mkts = await svc.cancel_tickets("buy", None)

        self.assertEqual(scoped["cancelled"], 1)
        self.assertEqual(all_mkts["cancelled"], 2)
        first = svc._signer.cancel_order.await_args_list[0].kwargs
        self.assertEqual((first["market_index"], first["order_index"]), (1, 1))
        rest = [
            (c.kwargs["market_index"], c.kwargs["order_index"])
            for c in svc._signer.cancel_order.await_args_list[1:]
        ]
        self.assertEqual(rest, [(1, 1), (2, 2)])

    async def test_empty_set_does_not_call_signer(self) -> None:
        svc = OrderService()
        svc._signer = MagicMock()
        svc._signer.cancel_order = AsyncMock(return_value=(None, "0xcan", None))
        rows = [
            _order(order_index=2, side="sell"),
            _order(
                order_index=3,
                side="buy",
                client_order_index=CHASE_COI_BASE + 3,
            ),
        ]

        with patch(
            "mayedge.lighter.orders.account_service.list_open_orders",
            return_value=rows,
        ):
            out = await svc.cancel_tickets("buy", None)

        self.assertEqual(out, {"cancelled": 0})
        svc._signer.cancel_order.assert_not_called()

    async def test_mid_batch_failure_keeps_earlier_cancels(self) -> None:
        svc = OrderService()
        svc._signer = MagicMock()
        svc._signer.cancel_order = AsyncMock(
            side_effect=[
                (None, "0x1", None),
                (None, None, "venue down"),
                (None, "0x3", None),
            ]
        )
        rows = [
            _order(order_index=1, side="buy"),
            _order(order_index=2, side="buy", client_order_index=1_000_000_002),
            _order(order_index=3, side="buy", client_order_index=1_000_000_003),
        ]

        with patch(
            "mayedge.lighter.orders.account_service.list_open_orders",
            return_value=rows,
        ):
            out = await svc.cancel_tickets("buy", None)

        self.assertEqual(out["cancelled"], 1)
        self.assertEqual(out["error"], "venue down")
        called = [c.kwargs["order_index"] for c in svc._signer.cancel_order.await_args_list]
        self.assertEqual(called, [1, 2])


class CancelAllOrdersTests(IsolatedAsyncioTestCase):
    def _signer(self) -> MagicMock:
        signer = MagicMock()
        signer.NIL_MARKET_INDEX = 255
        signer.CANCEL_ALL_TIF_IMMEDIATE = 0
        signer.cancel_all_orders = AsyncMock(
            return_value=(None, SimpleNamespace(code=200, tx_hash="0xall"), None)
        )
        return signer

    async def test_pair_immediate_cancel_sends_nil_time(self) -> None:
        """Immediate cancel-all: CancelAllTime must be nil (timestamp_ms=0)."""
        svc = OrderService()
        svc._signer = self._signer()
        await svc.cancel_all_orders(1)
        kw = svc._signer.cancel_all_orders.await_args.kwargs
        self.assertEqual(kw["timestamp_ms"], 0)
        self.assertEqual(kw["time_in_force"], 0)
        self.assertEqual(kw["cancel_all_market_index"], 1)

    async def test_all_markets_uses_nil_market_index(self) -> None:
        svc = OrderService()
        svc._signer = self._signer()
        await svc.cancel_all_orders(None)
        kw = svc._signer.cancel_all_orders.await_args.kwargs
        self.assertEqual(kw["timestamp_ms"], 0)
        self.assertEqual(kw["cancel_all_market_index"], 255)
