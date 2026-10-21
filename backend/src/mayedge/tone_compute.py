"""Tone math off the desk loop.

A 500-bar window holds the GIL for about 24 ms, past the 20 ms lag budget.
The worker process does not share the GIL, so a seed or a bar close cannot
stall the desk.

ponytail: one warm process. The ceiling on the loop is pickling one window
(under a millisecond at 500 bars). A thread would still hold the GIL.
"""

from __future__ import annotations

import asyncio
import multiprocessing
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from typing import Any

from mayedge.lighter.models import Candle
from mayedge.mayrekt import candle_tones

_pool: ProcessPoolExecutor | None = None


def _executor() -> ProcessPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ProcessPoolExecutor(
            max_workers=1,
            mp_context=multiprocessing.get_context("spawn"),
        )
    return _pool


def close(*, wait: bool = False) -> None:
    global _pool
    pool = _pool
    _pool = None
    if pool is not None:
        pool.shutdown(wait=wait, cancel_futures=not wait)


async def call(fn: Callable[..., Any], *args: Any) -> Any:
    """Run ``fn(*args)`` in the worker. A broken worker is replaced once."""
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(_executor(), fn, *args)
    except BrokenProcessPool:
        close()
        return await loop.run_in_executor(_executor(), fn, *args)


async def tones(bars: Sequence[Candle]) -> list[str | None]:
    found: list[str | None] = await call(candle_tones, list(bars))
    return found
