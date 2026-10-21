"""The heartbeat pings only while the desk is healthy, and never logs its URL."""

from __future__ import annotations

import asyncio
import unittest

import httpx

from mayedge.heartbeat import Heartbeat


class HeartbeatTests(unittest.IsolatedAsyncioTestCase):
    def _beat(
        self,
        url: str | None,
        sent: list[str],
        *,
        feeds: dict[str, object] | None = None,
        lag: float = 0,
        trading: bool = True,
        status: int = 200,
    ) -> tuple[Heartbeat, list[float]]:
        clock = {"t": 0.0}

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(str(request.url))
            if status >= 400:
                return httpx.Response(status)
            return httpx.Response(status)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(client.aclose)
        state = {"feeds": feeds or {"market_ws": "live", "account_ws": "live", "venue_down_since": 0}}

        async def sleep(seconds: float) -> None:
            clock["t"] += seconds
            sleeps.append(seconds)
            if len(sleeps) > 1:
                raise asyncio.CancelledError

        sleeps: list[float] = []
        beat = Heartbeat(
            url,
            client=client,
            sleep=sleep,
            now=lambda: clock["t"],
            feeds=lambda: state["feeds"],
            lag_ms=lambda: lag,
            trading=lambda: trading,
        )
        return beat, sleeps

    async def test_it_pings_every_minute_while_healthy_and_skips_when_it_is_not(self) -> None:
        url = "https://hc.example/ping/secret-token"
        sent: list[str] = []
        beat, sleeps = self._beat(url, sent)
        with self.assertLogs(level="DEBUG") as captured, self.assertRaises(asyncio.CancelledError):
            await beat.run()
        self.assertGreaterEqual(len(sent), 1)
        self.assertTrue(all(item == 60 for item in sleeps))
        self.assertEqual(beat.view(), {"on": True, "last_ok_at": 60_000})
        self.assertNotIn("secret-token", str(beat.view()))

        blob = "\n".join(record.getMessage() for record in captured.records)
        self.assertNotIn(url, blob)
        for record in captured.records:
            self.assertNotIn(url, str(record.args))

        async def quiet(feeds: dict[str, object], *, lag: float = 0, trading: bool = True) -> None:
            sent_quiet: list[str] = []
            one, _sleeps = self._beat(url, sent_quiet, feeds=feeds, lag=lag, trading=trading)
            with self.assertLogs(level="DEBUG"), self.assertRaises(asyncio.CancelledError):
                await one.run()
            self.assertEqual(sent_quiet, [])

        await quiet({"market_ws": "down", "account_ws": "live", "venue_down_since": 0})
        await quiet({"market_ws": "live", "account_ws": "down", "venue_down_since": 0}, trading=True)
        await quiet({"market_ws": "live", "account_ws": "live", "venue_down_since": 0}, lag=2000)
        await quiet({"market_ws": "live", "account_ws": "live", "venue_down_since": 50})

        sent_idle: list[str] = []
        idle, _sleeps = self._beat(
            url,
            sent_idle,
            feeds={"market_ws": "live", "account_ws": "down", "venue_down_since": 0},
            trading=False,
        )
        with self.assertLogs(level="DEBUG") as idle_logs, self.assertRaises(asyncio.CancelledError):
            await idle.run()
        self.assertEqual(sent_idle, [url])
        self.assertNotIn(url, "\n".join(record.getMessage() for record in idle_logs.records))

    async def test_an_unset_url_sends_nothing(self) -> None:
        sent: list[str] = []
        beat, _sleeps = self._beat(None, sent)
        with self.assertRaises(asyncio.CancelledError):
            await beat.run()
        self.assertEqual(sent, [])
        self.assertEqual(beat.view()["on"], False)

    async def test_a_failed_ping_does_not_log_the_url(self) -> None:
        url = "https://hc.example/ping/secret-token"
        sent: list[str] = []
        beat, _sleeps = self._beat(url, sent, status=500)
        with self.assertLogs(level="DEBUG") as captured, self.assertRaises(asyncio.CancelledError):
            await beat.run()
        self.assertTrue(sent)
        blob = "\n".join(record.getMessage() for record in captured.records)
        self.assertNotIn(url, blob)
        self.assertNotIn("secret-token", blob)
        self.assertTrue(
            any("heartbeat ping failed" in record.getMessage() for record in captured.records)
        )
        self.assertEqual(beat.view()["last_ok_at"], 0)


if __name__ == "__main__":
    unittest.main()
