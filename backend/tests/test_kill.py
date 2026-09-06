from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient

from mayedge.api.app import create_app
from mayedge.kill import kill
from mayedge.lighter.models import AccountSummary, Position
from mayedge.numbers import parse_decimal


class ParseDecimalKillTests(unittest.TestCase):
    def test_position_sizes(self) -> None:
        self.assertEqual(parse_decimal("1.5"), Decimal("1.5"))
        self.assertEqual(parse_decimal("-2"), Decimal("-2"))


class KillModuleTests(unittest.IsolatedAsyncioTestCase):
    async def test_partial_when_flatten_fails(self) -> None:
        chase = MagicMock()
        chase.stop = AsyncMock()

        orders = MagicMock()
        orders.enabled = True
        orders.kick_refresh = MagicMock()
        orders.cancel_all_orders = AsyncMock()
        orders.create_market_order = AsyncMock(side_effect=RuntimeError("venue down"))

        summary = AccountSummary(
            collateral="100",
            available="50",
            unrealized_pnl="0",
            positions=[
                Position(
                    market_index=1,
                    symbol="BTC",
                    size="1",
                    entry_price="100",
                    mark_price="100",
                    unrealized_pnl="0",
                    leverage=5,
                    margin_mode="cross",
                )
            ],
        )
        get_account_summary = AsyncMock(return_value=summary)

        result = await kill(
            flatten=True,
            chase=chase,
            orders=orders,
            get_account_summary=get_account_summary,
        )

        self.assertEqual(result.status, "partial")
        self.assertFalse(result.flatten[0]["ok"])
        chase.stop.assert_awaited_once()
        orders.cancel_all_orders.assert_awaited_once_with(None)

    async def test_kill_without_flatten_cancels_all(self) -> None:
        chase = MagicMock()
        chase.stop = AsyncMock()

        orders = MagicMock()
        orders.enabled = True
        orders.kick_refresh = MagicMock()
        orders.cancel_all_orders = AsyncMock()
        orders.create_market_order = AsyncMock()

        result = await kill(
            flatten=False,
            chase=chase,
            orders=orders,
            get_account_summary=AsyncMock(),
        )

        self.assertEqual(result.status, "killed")
        self.assertEqual(result.flatten, [])
        orders.cancel_all_orders.assert_awaited_once_with(None)
        orders.create_market_order.assert_not_called()


class KillSwitchEndpointTests(unittest.IsolatedAsyncioTestCase):
    @patch("mayedge.api.app.kill", new_callable=AsyncMock)
    async def test_http_kill_returns_module_result(self, kill_mock) -> None:
        from mayedge.kill import KillResult

        kill_mock.return_value = KillResult(
            status="killed",
            cancel_ok=True,
            cancel_error=None,
            flatten=[],
        )

        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post("/api/kill", json={"flatten": False})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["status"], "killed")
        self.assertIn("algos", body)
        self.assertNotIn("venue", body)
        kill_mock.assert_awaited_once()
        self.assertEqual(kill_mock.await_args.kwargs["flatten"], False)
