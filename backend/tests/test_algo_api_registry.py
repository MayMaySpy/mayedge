from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient

from mayedge.api.app import create_app


class AlgoApiRegistryTests(unittest.IsolatedAsyncioTestCase):
    @patch("mayedge.api.app.desk.start", new_callable=AsyncMock)
    @patch("mayedge.api.app.desk.restore", new_callable=AsyncMock)
    @patch("mayedge.api.app.desk.stop", new_callable=AsyncMock)
    async def test_start_unknown_algo_type_404(self, *_mocks) -> None:
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://localhost") as client:
            res = await client.post("/api/algos/unknown-algo/start", json={"market_index": 1})
        self.assertEqual(res.status_code, 404)

    @patch("mayedge.api.app.desk.start", new_callable=AsyncMock)
    @patch("mayedge.api.app.desk.restore", new_callable=AsyncMock)
    @patch("mayedge.api.app.desk.stop", new_callable=AsyncMock)
    @patch("mayedge.api.app.desk.get_book")
    @patch("mayedge.api.app.desk.algo_book", return_value={"type": "algo", "working": [], "history": []})
    @patch("mayedge.api.app.order_service")
    async def test_start_chase_delegates_to_book(
        self, order_service, algo_book, get_book, *_mocks
    ) -> None:
        order_service.enabled = True
        book = AsyncMock()
        book.start_from_body = AsyncMock()
        get_book.return_value = book
        app = create_app()
        transport = ASGITransport(app=app)
        body = {
            "market_index": 1,
            "side": "buy",
            "qty": "1",
            "display_qty": "0.1",
            "price_floor": "90",
            "price_ceiling": "110",
        }
        async with AsyncClient(transport=transport, base_url="http://localhost") as client:
            res = await client.post("/api/algos/chase-iceberg/start", json=body)
        self.assertEqual(res.status_code, 200)
        get_book.assert_called_with("chase-iceberg")
        book.start_from_body.assert_awaited_once_with(body)
        algo_book.assert_called_once()

    @patch("mayedge.api.app.desk.start", new_callable=AsyncMock)
    @patch("mayedge.api.app.desk.restore", new_callable=AsyncMock)
    @patch("mayedge.api.app.desk.stop", new_callable=AsyncMock)
    @patch("mayedge.api.app.desk.get_book")
    @patch("mayedge.api.app.order_service")
    async def test_start_chase_bad_params_400(self, order_service, get_book, *_mocks) -> None:
        order_service.enabled = True
        book = AsyncMock()
        book.start_from_body = AsyncMock(side_effect=ValueError("Set floor / ceiling"))
        get_book.return_value = book
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://localhost") as client:
            res = await client.post(
                "/api/algos/chase-iceberg/start",
                json={"market_index": 1, "side": "buy", "qty": "1", "display_qty": "0.1"},
            )
        self.assertEqual(res.status_code, 400)
        self.assertIn("Set floor / ceiling", res.json()["detail"])

    @patch("mayedge.api.app.desk.start", new_callable=AsyncMock)
    @patch("mayedge.api.app.desk.restore", new_callable=AsyncMock)
    @patch("mayedge.api.app.desk.stop", new_callable=AsyncMock)
    @patch("mayedge.api.app.desk.get_book")
    async def test_get_algo_type_returns_book_dict(self, get_book, *_mocks) -> None:
        book = MagicMock()
        book.to_dict.return_value = {"type": "algo", "id": "chase-iceberg", "working": [], "history": []}
        get_book.return_value = book
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://localhost") as client:
            res = await client.get("/api/algos/chase-iceberg")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["id"], "chase-iceberg")


class PlannerApiTests(unittest.IsolatedAsyncioTestCase):
    @patch("mayedge.api.app.desk.start", new_callable=AsyncMock)
    @patch("mayedge.api.app.desk.restore", new_callable=AsyncMock)
    @patch("mayedge.api.app.desk.stop", new_callable=AsyncMock)
    @patch("mayedge.api.app.desk.planner_book")
    async def test_preview_delegates_to_the_planner_book(self, planner_book, *_mocks) -> None:
        planner_book.preview_from_body = MagicMock(return_value={"plan": None, "refused": None})
        app = create_app()
        transport = ASGITransport(app=app)
        body = {"market_index": 1, "side": "buy", "stop": "95"}
        async with AsyncClient(transport=transport, base_url="http://localhost") as client:
            res = await client.post("/api/algos/planner/preview", json=body)
        self.assertEqual(res.status_code, 200)
        planner_book.preview_from_body.assert_called_once_with(body)

    @patch("mayedge.api.app.desk.start", new_callable=AsyncMock)
    @patch("mayedge.api.app.desk.restore", new_callable=AsyncMock)
    @patch("mayedge.api.app.desk.stop", new_callable=AsyncMock)
    @patch("mayedge.api.app.desk.planner_owns_exit", return_value=True)
    @patch("mayedge.api.app.order_service")
    async def test_the_stop_editor_refuses_on_a_planner_market(
        self, order_service, _owns, *_mocks
    ) -> None:
        order_service.enabled = True
        order_service.create_sl_tp = AsyncMock()
        app = create_app()
        transport = ASGITransport(app=app)
        body = {
            "market_index": 1,
            "side": "sell",
            "size": "0",
            "sl": {"kind": "market", "trigger": "90"},
        }
        async with AsyncClient(transport=transport, base_url="http://localhost") as client:
            res = await client.post("/api/orders/sl-tp", json=body)
        self.assertEqual(res.status_code, 409)
        order_service.create_sl_tp.assert_not_called()

