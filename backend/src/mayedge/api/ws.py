from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

logger = logging.getLogger(__name__)

BroadcastFn = Callable[[dict[str, Any]], Awaitable[None]]

# Unbounded Queue + a slow browser tab was filling RAM (multi-GB compressed).
_FANOUT_MAX = 512
_REPLACE_TYPES = frozenset({"account", "feed_health", "book_sync", "algo"})
_FLUSH_STATS = "_flush_stats"
_FLUSH_REPLACE = "_flush_replace"
_INTERNAL = frozenset({_FLUSH_STATS, _FLUSH_REPLACE})


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
    """Queue hub messages; one task drains to the WS broadcaster.

    High-churn types are coalesced (latest quote / account wins). The queue is
    bounded so a slow tab cannot retain the whole tape in RAM.
    """

    def __init__(self, broadcast: BroadcastFn) -> None:
        self._broadcast = broadcast
        self._queue: asyncio.Queue[dict[str, Any]] | None = None
        self._task: asyncio.Task[None] | None = None
        self._pending_replace: dict[str, dict[str, Any]] = {}
        self._replace_queued: set[str] = set()
        self._pending_stats: dict[int, dict[str, Any]] = {}
        self._stats_queued = False
        self._overflow_log_at = 0.0
        self.dropped = 0

    def start(self) -> None:
        if self._task is not None:
            return
        self._queue = asyncio.Queue()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        task = self._task
        self._task = None
        self._queue = None
        self._pending_replace.clear()
        self._replace_queued.clear()
        self._pending_stats.clear()
        self._stats_queued = False
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    def push(self, message: dict[str, Any]) -> None:
        q = self._queue
        if q is None:
            return
        kind = str(message.get("type") or "")
        if kind == "market_stats":
            for row in message.get("markets") or []:
                if not isinstance(row, dict):
                    continue
                raw_idx = row.get("market_index")
                if raw_idx is None:
                    continue
                try:
                    idx = int(raw_idx)
                except (TypeError, ValueError):
                    continue
                self._pending_stats[idx] = row
            if not self._stats_queued:
                self._stats_queued = True
                self._put(q, {"type": _FLUSH_STATS})
            return
        if kind in _REPLACE_TYPES:
            self._pending_replace[kind] = message
            if kind not in self._replace_queued:
                self._replace_queued.add(kind)
                self._put(q, {"type": _FLUSH_REPLACE, "slot": kind})
            return
        self._put(q, message)

    def _put(self, q: asyncio.Queue[dict[str, Any]], message: dict[str, Any]) -> None:
        parked: list[dict[str, Any]] = []
        while q.qsize() >= _FANOUT_MAX:
            try:
                item = q.get_nowait()
            except asyncio.QueueEmpty:
                break
            if item.get("type") in _INTERNAL:
                parked.append(item)
                continue
            self.dropped += 1
            now = time.monotonic()
            if now - self._overflow_log_at >= 10:
                self._overflow_log_at = now
                logger.warning(
                    "fanout overflow — dropped %s (total dropped=%s q=%s)",
                    item.get("type"),
                    self.dropped,
                    q.qsize(),
                )
            break
        for item in parked:
            try:
                q.put_nowait(item)
            except Exception:
                logger.exception("fanout requeue internal failed")
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
                kind = msg.get("type")
                try:
                    if kind == _FLUSH_STATS:
                        self._stats_queued = False
                        rows = list(self._pending_stats.values())
                        self._pending_stats.clear()
                        if rows:
                            await self._broadcast({"type": "market_stats", "markets": rows})
                        continue
                    if kind == _FLUSH_REPLACE:
                        slot = str(msg.get("slot") or "")
                        self._replace_queued.discard(slot)
                        payload = self._pending_replace.pop(slot, None)
                        if payload:
                            await self._broadcast(payload)
                        continue
                    await self._broadcast(msg)
                except Exception:
                    logger.exception("fanout broadcast failed")
        except asyncio.CancelledError:
            raise


manager = ConnectionManager()
