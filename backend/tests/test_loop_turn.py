"""A page of HTTP handlers must not add their times into one lag tick."""

from __future__ import annotations

import asyncio
import time
import unittest
from typing import Any, cast

from starlette.types import Receive, Scope, Send

from mayedge.api.turn import LoopTurn


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


async def _receive() -> Any:
    return {"type": "http.request", "body": b"", "more_body": False}


async def _send(message: Any) -> None:
    del message
