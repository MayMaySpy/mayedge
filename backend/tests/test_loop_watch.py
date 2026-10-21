"""Loop lag is late-wake time, and a warning fires at most once a minute."""

from __future__ import annotations

import unittest

from mayedge.loop_watch import LoopWatch


class _Clock:
    def __init__(self) -> None:
        self.mono_s = 0.0
        self.wall = 0.0
        self.late = 0.0

    def now(self) -> float:
        return self.wall

    def mono(self) -> float:
        return self.mono_s

    async def sleep(self, seconds: float) -> None:
        self.mono_s += seconds + self.late
        self.wall += seconds + self.late


class LoopWatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_lag_is_how_late_the_wake_was(self) -> None:
        clock = _Clock()
        clock.late = 0.04
        watch = LoopWatch(clock)
        await watch._tick()
        self.assertAlmostEqual(watch.snapshot()["loop_lag_ms"], 40.0, places=3)
        self.assertAlmostEqual(watch.snapshot()["loop_lag_max_60s_ms"], 40.0, places=3)

    async def test_the_60s_max_rolls_off(self) -> None:
        clock = _Clock()
        watch = LoopWatch(clock)
        clock.late = 0.1
        await watch._tick()
        self.assertAlmostEqual(watch.snapshot()["loop_lag_max_60s_ms"], 100.0, places=3)
        clock.late = 0.0
        clock.mono_s += 61
        await watch._tick()
        self.assertEqual(watch.snapshot()["loop_lag_max_60s_ms"], 0.0)
        self.assertEqual(watch.snapshot()["loop_lag_ms"], 0.0)

    async def test_a_late_warning_is_one_a_minute(self) -> None:
        clock = _Clock()
        clock.late = 0.3
        watch = LoopWatch(clock)
        with self.assertLogs("mayedge.loop_watch", level="WARNING") as first:
            await watch._tick()
            await watch._tick()
        self.assertEqual(len(first.output), 1)
        self.assertIn("300", first.output[0])
        clock.mono_s += 60
        with self.assertLogs("mayedge.loop_watch", level="WARNING") as second:
            await watch._tick()
        self.assertEqual(len(second.output), 1)
