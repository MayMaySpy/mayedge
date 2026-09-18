from __future__ import annotations

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from mayedge.algos.chase.config import CHASE_COI_BASE
from mayedge.lighter.models import MarketMeta, OpenOrder
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


def _ticket() -> OpenOrder:
    return OpenOrder(
        order_index=42,
        client_order_index=1_000_000_001,
        market_index=1,
        symbol="ETH",
        side="buy",
        price="100.00",
        size="0.5",
        remaining="0.4",
        order_type="limit",
        reduce_only=False,
    )


class AmendTicketTests(IsolatedAsyncioTestCase):
    async def test_amends_a_ticket_with_remaining_size(self) -> None:
        svc = OrderService()
        svc._signer = MagicMock()
        svc._signer.modify_order = AsyncMock(return_value=(None, "0xmod", None))
        live = _ticket()

        with (
            patch.object(svc, "_market_meta", return_value=_eth()),
            patch(
                "mayedge.lighter.orders.account_service.find_open_order",
                return_value=live,
            ),
        ):
            out = await svc.amend_ticket(1, 42, "101.25")

        self.assertEqual(out["tx_hash"], "0xmod")
        call = svc._signer.modify_order.await_args.kwargs
        self.assertEqual(call["market_index"], 1)
        self.assertEqual(call["order_index"], 42)
        self.assertEqual(call["price"], 10125)
        self.assertEqual(call["base_amount"], 4)

    async def test_rejects_a_clip(self) -> None:
        svc = OrderService()
        svc._signer = MagicMock()
        svc._signer.modify_order = AsyncMock(return_value=(None, "0xmod", None))
        clip = _ticket()
        clip.client_order_index = CHASE_COI_BASE + 3

        with patch(
            "mayedge.lighter.orders.account_service.find_open_order",
            return_value=clip,
        ), self.assertRaisesRegex(ValueError, "Clip"):
            await svc.amend_ticket(1, 42, "101.25")

        svc._signer.modify_order.assert_not_called()

    async def test_rejects_a_missing_order(self) -> None:
        svc = OrderService()
        svc._signer = MagicMock()
        svc._signer.modify_order = AsyncMock()

        with patch(
            "mayedge.lighter.orders.account_service.find_open_order",
            return_value=None,
        ), self.assertRaisesRegex(ValueError, "not found"):
            await svc.amend_ticket(1, 42, "101.25")

        svc._signer.modify_order.assert_not_called()
