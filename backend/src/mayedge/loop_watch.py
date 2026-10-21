"""How late the desk's event loop woke a timer it set."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from collections import deque
from collections.abc import Callable
from typing import Any, Protocol

logger = logging.getLogger(__name__)

_TICK_S = 0.25
_WINDOW_S = 60.0
_WARN_MS = 250.0
_FREEZE_S = 30.0


class Clock(Protocol):
    def now(self) -> float: ...

    def mono(self) -> float: ...

    async def sleep(self, seconds: float) -> None: ...


class _LoopClock:
    """Production clock: mono is the loop clock the 250 ms sleep runs on."""

    def now(self) -> float:
        return time.time()

    def mono(self) -> float:
        return asyncio.get_running_loop().time()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class LoopWatch:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self._samples: deque[tuple[float, float]] = deque()
        self._warned_at: float | None = None
        self._last_freeze: dict[str, int] | None = None
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self.run(), name="loop-lag")

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        self._task = None

    async def run(self) -> None:
        while True:
            await self._tick()

    async def _tick(self) -> None:
        wall_before = self.clock.now()
        mono_before = self.clock.mono()
        expected = mono_before + _TICK_S
        await self.clock.sleep(_TICK_S)
        actual = self.clock.mono()
        wall_after = self.clock.now()
        lag_ms = max(0.0, (actual - expected) * 1000.0)
        self._samples.append((actual, lag_ms))
        self._prune(actual)
        if lag_ms > _WARN_MS and (self._warned_at is None or actual - self._warned_at >= _WINDOW_S):
            logger.warning("event loop lag %.0f ms", lag_ms)
            self._warned_at = actual
        self._note_freeze(wall_before, wall_after, actual - mono_before)

    def _note_freeze(self, wall_before: float, wall_after: float, mono_jump: float) -> None:
        wall_jump = wall_after - wall_before
        if wall_jump <= _FREEZE_S:
            return
        wall_alone = wall_jump - mono_jump > _FREEZE_S
        mono_missed = mono_jump > _TICK_S + _FREEZE_S
        if not wall_alone and not mono_missed:
            return
        event = {
            "type": "desk_freeze",
            "from": round(wall_before * 1000),
            "to": round(wall_after * 1000),
        }
        self._last_freeze = {"from": event["from"], "to": event["to"]}
        if _freeze_emit is not None:
            _freeze_emit(event)

    def _prune(self, now: float) -> None:
        while self._samples and now - self._samples[0][0] >= _WINDOW_S:
            self._samples.popleft()

    def snapshot(self) -> dict[str, Any]:
        self._prune(self.clock.mono())
        if not self._samples:
            lags: dict[str, Any] = {"loop_lag_ms": 0.0, "loop_lag_max_60s_ms": 0.0}
        else:
            lags = {
                "loop_lag_ms": self._samples[-1][1],
                "loop_lag_max_60s_ms": max(lag for _stamp, lag in self._samples),
            }
        lags["last_freeze"] = self._last_freeze
        return lags


_active: LoopWatch | None = None
_freeze_emit: Callable[[dict[str, Any]], None] | None = None


def set_freeze_emitter(fn: Callable[[dict[str, Any]], None] | None) -> None:
    global _freeze_emit
    _freeze_emit = fn


def snapshot() -> dict[str, Any]:
    if _active is None:
        return {"loop_lag_ms": 0.0, "loop_lag_max_60s_ms": 0.0, "last_freeze": None}
    return _active.snapshot()


def start_loop_watch(clock: Clock | None = None) -> LoopWatch:
    global _active
    if os.environ.get("MAYEDGE_ASYNCIO_DEBUG") == "1":
        loop = asyncio.get_running_loop()
        loop.set_debug(True)
        loop.slow_callback_duration = 0.05
    watch = LoopWatch(clock or _LoopClock())
    watch.start()
    _active = watch
    return watch
