"""The desk has no login, so it must not answer to other sites in the operator's browser."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from starlette.websockets import WebSocketDisconnect

from mayedge.api.app import create_app
from mayedge.api.guard import host_allowed, origin_allowed

HOSTS = ["localhost", "127.0.0.1", "[::1]", "*.ts.net"]


class HostRuleTests(unittest.TestCase):
    def test_loopback_and_tailnet_names_pass(self) -> None:
        for host in (
            "localhost:5173",
            "127.0.0.1:14200",
            "[::1]:8000",
            "desk.tail1234.ts.net",
            "LOCALHOST",
        ):
            self.assertTrue(host_allowed(host, HOSTS), host)

    def test_other_names_are_refused(self) -> None:
        for host in ("attacker.example", "ts.net.attacker.example", "evil-ts.net", ""):
            self.assertFalse(host_allowed(host, HOSTS), host)


class OriginRuleTests(unittest.TestCase):
    def test_the_page_the_desk_was_served_as_passes(self) -> None:
        self.assertTrue(origin_allowed("http://127.0.0.1:14200", ["127.0.0.1:14200"], []))
        self.assertTrue(
            origin_allowed("https://desk.tail1234.ts.net", ["desk.tail1234.ts.net"], [])
        )

    def test_a_proxy_that_rewrites_host_is_matched_by_forwarded_host(self) -> None:
        self.assertTrue(
            origin_allowed(
                "https://desk.tail1234.ts.net",
                ["127.0.0.1:14200", "desk.tail1234.ts.net"],
                [],
            )
        )

    def test_a_configured_dev_origin_passes(self) -> None:
        self.assertTrue(
            origin_allowed("http://localhost:5173", ["127.0.0.1:8000"], ["http://localhost:5173"])
        )

    def test_another_site_is_refused(self) -> None:
        served = ["127.0.0.1:14200"]
        for origin in (
            "https://evil.example",
            "http://localhost:3000",
            "https://other.tail9999.ts.net",
            "null",
        ):
            self.assertFalse(origin_allowed(origin, served, []), origin)


class GuardedAppTests(unittest.IsolatedAsyncioTestCase):
    async def _client(self) -> AsyncClient:
        return AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://localhost")

    async def test_another_site_cannot_stop_algos(self) -> None:
        with patch("mayedge.api.app.desk.stop_algo", new_callable=AsyncMock) as stop:
            async with await self._client() as client:
                res = await client.post(
                    "/api/algos/stop", headers={"Origin": "https://evil.example"}
                )
        self.assertEqual(res.status_code, 403)
        stop.assert_not_called()

    async def test_the_desk_page_can_stop_algos(self) -> None:
        with patch("mayedge.api.app.desk.stop_algo", new_callable=AsyncMock) as stop:
            stop.return_value = {"type": "algo"}
            async with await self._client() as client:
                res = await client.post("/api/algos/stop", headers={"Origin": "http://localhost"})
        self.assertEqual(res.status_code, 200)
        stop.assert_awaited_once()

    async def test_a_request_without_origin_passes(self) -> None:
        with patch("mayedge.api.app.desk.stop_algo", new_callable=AsyncMock) as stop:
            stop.return_value = {"type": "algo"}
            async with await self._client() as client:
                res = await client.post("/api/algos/stop")
        self.assertEqual(res.status_code, 200)

    async def test_a_rebound_host_is_refused_even_for_reads(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=create_app()), base_url="http://attacker.example"
        ) as client:
            res = await client.get("/api/health")
        self.assertEqual(res.status_code, 400)

    async def test_reads_from_the_desk_host_pass(self) -> None:
        async with await self._client() as client:
            res = await client.get("/api/health", headers={"Origin": "https://evil.example"})
        # Reads are left to CORS: the browser will not hand this response to that page.
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("access-control-allow-origin", res.headers)


class GuardedSocketTests(unittest.TestCase):
    def test_another_site_cannot_open_the_feed(self) -> None:
        client = TestClient(create_app(), base_url="http://localhost")
        with (
            self.assertRaises(WebSocketDisconnect),
            client.websocket_connect("ws://localhost/ws", headers={"Origin": "https://evil.example"}),
        ):
            pass

    def test_a_rebound_host_cannot_open_the_feed(self) -> None:
        client = TestClient(create_app())
        with (
            self.assertRaises(WebSocketDisconnect),
            client.websocket_connect("ws://attacker.example/ws"),
        ):
            pass

    def test_the_desk_page_opens_the_feed(self) -> None:
        client = TestClient(create_app(), base_url="http://localhost")
        with client.websocket_connect("ws://localhost/ws", headers={"Origin": "http://localhost"}) as ws:
            self.assertEqual(ws.receive_json()["type"], "init")
