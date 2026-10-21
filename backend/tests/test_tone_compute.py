"""Tone math for a full window runs off the desk loop."""

from __future__ import annotations

import asyncio
import unittest
from collections.abc import Awaitable

from mayedge.lighter.models import Candle
from mayedge.tone_alerts import ToneBook
from mayedge.tone_compute import close


def _bars(n: int) -> list[Candle]:
    px = 100.0
    out: list[Candle] = []
    for i in range(n):
        px += 0.05
        out.append(Candle(1_700_000_000 + i * 60, px - 0.4, px + 0.8, px - 0.9, px, 1_000 + i))
    return out


async def _max_loop_gap_ms(awaitable: Awaitable[object]) -> float:
    """How late a 10 ms loop timer woke. A stall on this thread must count."""
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
        await awaitable
    finally:
        stop.set()
        await task
    return max(gaps, default=0.0)


class ToneOffLoopTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        close(wait=True)

    async def test_a_full_window_matches_and_lets_the_loop_run(self) -> None:
        bars = _bars(500)
        now = bars[-1].time + 120
        sync = ToneBook(timeframes=("1m",))
        off = ToneBook(timeframes=("1m",))
        sync.seed(1, "1m", bars, now=now)
        gap = await _max_loop_gap_ms(off.seed_off_loop(1, "1m", bars, now=now))
        self.assertEqual(off.board(), sync.board())
        # On the loop this window is about 24 ms, over the desk's 20 ms budget.
        self.assertLess(gap, 20.0)

        last = bars[-1].time
        extra = [
            Candle(last + 60, 130, 131, 129, 130.5, 2),
            Candle(last + 120, 131, 132, 130, 131.5, 2),
        ]
        sync.observe(1, "1m", extra, now=last + 130)
        gap = await _max_loop_gap_ms(off.observe_off_loop(1, "1m", extra, now=last + 130))
        self.assertEqual(off.board(), sync.board())
        self.assertLess(gap, 20.0)
