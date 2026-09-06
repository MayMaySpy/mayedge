from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

logger = logging.getLogger(__name__)

BroadcastFn = Callable[[dict[str, Any]], Awaitable[None]]


def ws_connected(ws: WebSocket) -> bool:
    return (
        ws.client_state == WebSocketState.CONNECTED
        and ws.application_state == WebSocketState.CONNECTED
    )


def _closed_runtime(exc: RuntimeError) -> bool:
    msg = str(exc).lower()
    return "close message" in msg or "not connected" in msg


async def send_json(ws: WebSocket, payload: dict[str, Any]) -> None:
    """Send JSON, mapping a client that already left to WebSocketDisconnect."""
    if not ws_connected(ws):
        raise WebSocketDisconnect()
    try:
        await ws.send_json(payload)
    except RuntimeError as e:
        if _closed_runtime(e):
            raise WebSocketDisconnect() from e
        raise


class ConnectionManager:
    def __init__(self) -> None:
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, message: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        clients = list(self.active)
        for ws in clients:
            try:
                await send_json(ws, message)
            except (WebSocketDisconnect, Exception):
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


class BroadcastFanout:
    """Queue hub messages; one task drains to the WS broadcaster."""

    def __init__(self, broadcast: BroadcastFn) -> None:
        self._broadcast = broadcast
        self._queue: asyncio.Queue[dict[str, Any]] | None = None
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is not None:
            return
        self._queue = asyncio.Queue()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        task = self._task
        self._task = None
        self._queue = None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    def push(self, message: dict[str, Any]) -> None:
        q = self._queue
        if q is None:
            return
        try:
            q.put_nowait(message)
        except Exception:
            logger.exception("fanout push failed")

    async def _run(self) -> None:
        q = self._queue
        if q is None:
            return
        try:
            while True:
                msg = await q.get()
                try:
                    await self._broadcast(msg)
                except Exception:
                    logger.exception("fanout broadcast failed")
        except asyncio.CancelledError:
            raise


manager = ConnectionManager()
