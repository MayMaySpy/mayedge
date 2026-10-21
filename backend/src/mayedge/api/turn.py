"""One chunk of desk work per loop turn.

A page open finishes many HTTP handlers and websocket sends in one turn, and
their times add into the lag. A zero-delay timer waits behind a timer that is
already due, so the lag tick runs between chunks. The ceiling is a single
handler or a single send.
"""

from __future__ import annotations

import asyncio

from starlette.types import ASGIApp, Receive, Scope, Send

_tail: asyncio.Future[None] | None = None
_loop: asyncio.AbstractEventLoop | None = None


# ponytail: a market-feed callback that never awaits can still share the turn.
# Split that callback if a later sample shows it over 20 ms.
async def breathe() -> None:
    """Wait until the chunk ahead has yielded, then let a due lag tick run."""
    global _tail, _loop
    loop = asyncio.get_running_loop()
    if _loop is not loop:
        _tail = None
        _loop = loop
    prev = _tail
    mine: asyncio.Future[None] = loop.create_future()
    _tail = mine
    try:
        if prev is not None and not prev.done():
            await prev
        ready: asyncio.Future[None] = loop.create_future()
        handle = loop.call_later(0, _wake, ready)
        try:
            await ready
        except asyncio.CancelledError:
            handle.cancel()
            raise
    finally:
        if not mine.done():
            mine.set_result(None)


def _wake(ready: asyncio.Future[None]) -> None:
    # A waiter cancelled before this timer runs has already cancelled `ready`.
    if not ready.done():
        ready.set_result(None)


class LoopTurn:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            await breathe()
        await self.app(scope, receive, send)
