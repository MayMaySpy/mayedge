from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from mayedge.api.app import create_app
from mayedge.config import settings


class ApiContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_venues_endpoint_removed(self) -> None:
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://localhost") as client:
            res = await client.get("/api/venues")
        self.assertEqual(res.status_code, 404)

    @patch("mayedge.api.app.desk.start", new_callable=AsyncMock)
    @patch("mayedge.api.app.desk.restore", new_callable=AsyncMock)
    @patch("mayedge.api.app.desk.stop", new_callable=AsyncMock)
    async def test_health_has_no_venue_fields(self, *_mocks) -> None:
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://localhost") as client:
            res = await client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertNotIn("venues", body)
        self.assertNotIn("focus", body)
        self.assertIn("network", body)
        self.assertIn("trading_enabled", body)
        self.assertEqual(body["network"], settings.lighter_network.value)

    @patch("mayedge.api.app.desk.start", new_callable=AsyncMock)
    @patch("mayedge.api.app.desk.restore", new_callable=AsyncMock)
    @patch("mayedge.api.app.desk.stop", new_callable=AsyncMock)
    @patch("mayedge.lighter.gateway.gateway.list_markets", return_value=[])
    async def test_markets_ignores_venue_query(self, *_mocks) -> None:
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://localhost") as client:
            res = await client.get("/api/markets?venue=lighter")
        self.assertEqual(res.status_code, 200)
        self.assertIsInstance(res.json(), list)


class ReadErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_an_unknown_market_is_404_not_500(self) -> None:
        transport = ASGITransport(app=create_app())
        async with AsyncClient(transport=transport, base_url="http://localhost") as client:
            candles = await client.get("/api/candles/NOPE")
            activate = await client.post("/api/markets/NOPE/activate")
        self.assertEqual(candles.status_code, 404)
        self.assertEqual(activate.status_code, 404)

    async def test_a_refused_read_is_429_not_500(self) -> None:
        from mayedge.lighter.budget import BudgetRefused

        transport = ASGITransport(app=create_app())
        with (
            patch("mayedge.api.app.gateway.resolve_market_index", return_value=1),
            patch(
                "mayedge.api.app.gateway.get_candles",
                new_callable=AsyncMock,
                side_effect=BudgetRefused(429, "Lighter rate limit — retry shortly (12s)"),
            ),
        ):
            async with AsyncClient(transport=transport, base_url="http://localhost") as client:
                res = await client.get("/api/candles/BTC")
        self.assertEqual(res.status_code, 429)
        self.assertIn("rate limit", res.json()["detail"])
