"""An outbound ping while the desk is healthy. Off unless a URL is set."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from mayedge.config import settings

logger = logging.getLogger(__name__)

# The URL is a secret. httpx would log it at INFO.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

PING_S = 60.0
WARN_S = 600.0
_current: Heartbeat | None = None


class Heartbeat:
    def __init__(
        self,
        url: str | None,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now: Callable[[], float] = time.time,
        feeds: Callable[[], dict[str, Any]] | None = None,
        lag_ms: Callable[[], float] | None = None,
        trading: Callable[[], bool] | None = None,
    ) -> None:
        self._url = url or None
        self._client = client
        self._sleep = sleep
        self._now = now
        self._feeds = feeds or (lambda: {})
        self._lag_ms = lag_ms or (lambda: 0.0)
        self._trading = trading or (lambda: False)
        self._last_ok_at = 0
        self._warned_at: float | None = None

    def view(self) -> dict[str, bool | int]:
        return {"on": self._url is not None, "last_ok_at": self._last_ok_at}

    def _skip(self) -> str | None:
        feeds = self._feeds()
        if feeds.get("market_ws") != "live":
            return "market feed not live"
        if self._trading() and feeds.get("account_ws") != "live":
            return "account feed not live"
        if self._lag_ms() >= 2000:
            return "loop lag"
        if feeds.get("venue_down_since"):
            return "venue down"
        return None

    async def _ping(self) -> None:
        client = self._client
        url = self._url
        if client is None or url is None:
            return
        try:
            response = await client.get(url)
            response.raise_for_status()
        except Exception:
            now = self._now()
            if self._warned_at is None or now - self._warned_at >= WARN_S:
                logger.warning("heartbeat ping failed")
                self._warned_at = now
            return
        self._last_ok_at = int(self._now() * 1000)
        logger.debug("heartbeat ok")

    async def run(self) -> None:
        while True:
            await self._sleep(PING_S)
            if self._url is None:
                continue
            reason = self._skip()
            if reason:
                logger.debug("heartbeat skipped: %s", reason)
                continue
            await self._ping()


def heartbeat_view() -> dict[str, bool | int]:
    if _current is None:
        return {"on": bool(settings.heartbeat_url), "last_ok_at": 0}
    return _current.view()


def start_heartbeat() -> asyncio.Task[None]:
    global _current
    from mayedge import feed_health
    from mayedge.loop_watch import snapshot as loop_snapshot

    client = httpx.AsyncClient(timeout=10) if settings.heartbeat_url else None
    beat = Heartbeat(
        settings.heartbeat_url,
        client=client,
        feeds=feed_health.snapshot,
        lag_ms=lambda: float(loop_snapshot().get("loop_lag_max_60s_ms") or 0),
        trading=lambda: settings.trading_enabled,
    )
    _current = beat

    async def _run() -> None:
        global _current
        try:
            await beat.run()
        finally:
            if _current is beat:
                _current = None
            if client is not None:
                await client.aclose()

    return asyncio.create_task(_run(), name="heartbeat")
