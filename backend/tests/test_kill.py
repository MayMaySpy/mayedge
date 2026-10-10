from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient

from mayedge.api.app import _account_summary_for_kill, create_app
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
            algos=chase,
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
            algos=chase,
            orders=orders,
            get_account_summary=AsyncMock(),
        )

        self.assertEqual(result.status, "killed")
        self.assertEqual(result.flatten, [])
        orders.cancel_all_orders.assert_awaited_once_with(None)
        orders.create_market_order.assert_not_called()


    async def test_a_book_that_will_not_stop_does_not_hold_up_the_rest(self) -> None:
        algos = MagicMock()
        algos.stop = AsyncMock(side_effect=RuntimeError("grid would not stop"))

        orders = MagicMock()
        orders.enabled = True
        orders.cancel_all_orders = AsyncMock()
        orders.create_market_order = AsyncMock()

        summary = AccountSummary(
            collateral="100",
            available="50",
            unrealized_pnl="0",
            positions=[
                Position(
                    market_index=1,
                    symbol="BTC",
                    size="-2",
                    entry_price="100",
                    mark_price="100",
                    unrealized_pnl="0",
                    leverage=5,
                    margin_mode="cross",
                )
            ],
        )

        result = await kill(
            flatten=True,
            algos=algos,
            orders=orders,
            get_account_summary=AsyncMock(return_value=summary),
            slippage=0.02,
        )

        self.assertEqual(result.status, "partial")
        self.assertEqual(result.algo_error, "grid would not stop")
        orders.cancel_all_orders.assert_awaited_once_with(None)
        orders.create_market_order.assert_awaited_once_with(1, "buy", "2", 0.02, True)
        self.assertTrue(result.flatten[0]["ok"])


class StopEveryBookTests(unittest.IsolatedAsyncioTestCase):
    async def test_desk_stops_the_other_books_when_one_fails(self) -> None:
        from mayedge import desk

        bad = MagicMock()
        bad.stop = AsyncMock(side_effect=RuntimeError("venue down"))
        good = MagicMock()
        good.stop = AsyncMock()
        with patch.object(desk, "books", (bad, good)), self.assertRaises(RuntimeError):
            await desk.stop_algo()
        good.stop.assert_awaited_once_with(None)

    async def test_a_book_stops_its_other_jobs_when_one_fails(self) -> None:
        from mayedge.algos.chase.book import ChaseBook

        book = ChaseBook(execution=MagicMock(), broadcast=lambda _payload: None)
        bad = MagicMock()
        bad.stop = AsyncMock(side_effect=RuntimeError("cancel failed"))
        good = MagicMock()
        good.stop = AsyncMock()
        book._jobs = {"CH-0001": bad, "CH-0002": good}
        with self.assertRaises(RuntimeError):
            await book.stop()
        good.stop.assert_awaited_once()


class AccountSummaryForKillTests(unittest.IsolatedAsyncioTestCase):
    @patch("mayedge.api.app.order_service")
    @patch("mayedge.api.app.account_service")
    async def test_falls_back_to_cache_when_rest_fails(
        self, account_svc, order_svc
    ) -> None:
        order_svc.get_account_summary = AsyncMock(side_effect=RuntimeError("budget"))
        cached = AccountSummary(collateral="1", available="1", unrealized_pnl="0")
        account_svc.cached_summary.return_value = cached
        got = await _account_summary_for_kill()
        self.assertIs(got, cached)


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
        async with AsyncClient(transport=transport, base_url="http://localhost") as client:
            res = await client.post("/api/kill", json={"flatten": False})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["status"], "killed")
        self.assertIn("algos", body)
        self.assertNotIn("venue", body)
        kill_mock.assert_awaited_once()
        self.assertEqual(kill_mock.await_args.kwargs["flatten"], False)
