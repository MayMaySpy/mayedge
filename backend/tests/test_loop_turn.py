"""A page of HTTP handlers must not add their times into one lag tick."""

from __future__ import annotations

import asyncio
import time
import unittest
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

from starlette.types import Receive, Scope, Send
from starlette.websockets import WebSocketState

from mayedge.api.turn import LoopTurn, _wake
from mayedge.api.ws import send_json


async def _gap(awaitable: object) -> float:
    gaps: list[float] = []
    stop = asyncio.Event()

    async def ticker() -> None:
        loop = asyncio.get_running_loop()
        prev = loop.time()
        while not stop.is_set():
            await asyncio.sleep(0.01)
            now = loop.time()
            gaps.append((now - prev - 0.01) * 1000)
            prev = now

    task = asyncio.create_task(ticker())
    await asyncio.sleep(0.02)
    try:
        await awaitable  # type: ignore[misc]
    finally:
        stop.set()
        await task
    return max(gaps, default=0.0)


class LoopTurnTests(unittest.IsolatedAsyncioTestCase):
    async def test_four_handlers_do_not_add_up(self) -> None:
        ran = 0

        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            del scope, receive, send
            nonlocal ran
            end = time.perf_counter() + 0.015
            while time.perf_counter() < end:
                pass
            ran += 1

        turn = LoopTurn(app)

        async def once() -> None:
            await turn(cast(Scope, {"type": "http"}), _receive, _send)

        gap = await _gap(asyncio.gather(once(), once(), once(), once()))
        self.assertEqual(ran, 4)
        # Four 15 ms handlers in one turn would be about 60 ms.
        self.assertLess(gap, 20.0)

    async def test_sends_do_not_add_up_with_handlers(self) -> None:
        async def burn(_payload: object) -> None:
            end = time.perf_counter() + 0.015
            while time.perf_counter() < end:
                pass

        def socket() -> MagicMock:
            ws = MagicMock()
            ws.client_state = WebSocketState.CONNECTED
            ws.application_state = WebSocketState.CONNECTED
            ws.send_json = AsyncMock(side_effect=burn)
            return ws

        async def once_send() -> None:
            await send_json(socket(), {"type": "init"})

        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            del scope, receive, send
            end = time.perf_counter() + 0.015
            while time.perf_counter() < end:
                pass

        turn = LoopTurn(app)

        async def once_http() -> None:
            await turn(cast(Scope, {"type": "http"}), _receive, _send)

        gap = await _gap(
            asyncio.gather(once_http(), once_http(), once_send(), once_send())
        )
        self.assertLess(gap, 20.0)


async def _receive() -> Any:
    return {"type": "http.request", "body": b"", "more_body": False}


async def _send(message: Any) -> None:
    del message


class WakeTests(unittest.TestCase):
    def test_a_cancelled_waiter_is_not_woken(self) -> None:
        loop = asyncio.new_event_loop()
        try:
            ready: asyncio.Future[None] = loop.create_future()
            ready.cancel()
            _wake(ready)
            self.assertTrue(ready.cancelled())
        finally:
            loop.close()
