"""One HTTP handler per loop turn.

A page open finishes many requests in one turn, and their times add into the
lag. A zero-delay timer waits behind a timer that is already due, so the lag
tick runs between handlers. The ceiling is a single handler.

WebSockets are not queued. Their sends already await.
"""

from __future__ import annotations

import asyncio

from starlette.types import ASGIApp, Receive, Scope, Send


class LoopTurn:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._tail: asyncio.Future[None] | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        loop = asyncio.get_running_loop()
        prev = self._tail
        mine: asyncio.Future[None] = loop.create_future()
        self._tail = mine
        try:
            if prev is not None:
                await prev
            ready: asyncio.Future[None] = loop.create_future()
            handle = loop.call_later(0, ready.set_result, None)
            try:
                await ready
            except asyncio.CancelledError:
                handle.cancel()
                raise
        finally:
            if not mine.done():
                mine.set_result(None)
        await self.app(scope, receive, send)
