"""Loop lag is late-wake time, and a warning fires at most once a minute."""

from __future__ import annotations

import unittest

from mayedge.loop_watch import LoopWatch


class _Clock:
    def __init__(self) -> None:
        self.mono_s = 0.0
        self.wall = 0.0
        self.late = 0.0
        self.wall_extra = 0.0

    def now(self) -> float:
        return self.wall

    def mono(self) -> float:
        return self.mono_s

    async def sleep(self, seconds: float) -> None:
        self.mono_s += seconds + self.late
        self.wall += seconds + self.late + self.wall_extra


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


class FreezeTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        from mayedge.loop_watch import set_freeze_emitter

        set_freeze_emitter(None)

    async def test_a_wall_jump_the_loop_missed_is_one_freeze(self) -> None:
        from mayedge.loop_watch import set_freeze_emitter

        clock = _Clock()
        clock.wall = 1_000.0
        clock.wall_extra = 2 * 3600
        events: list[dict[str, object]] = []
        set_freeze_emitter(events.append)
        watch = LoopWatch(clock)
        await watch._tick()
        freeze = watch.snapshot()["last_freeze"]
        self.assertEqual(len(events), 1)
        self.assertEqual(freeze["from"], 1_000_000)
        self.assertEqual(freeze["to"], events[0]["to"])
        self.assertGreater(int(freeze["to"]) - int(freeze["from"]), 30_000)

    async def test_both_clocks_jumping_is_a_freeze_and_a_stall_is_not(self) -> None:
        clock = _Clock()
        clock.late = 3
        watch = LoopWatch(clock)
        await watch._tick()
        self.assertIsNone(watch.snapshot()["last_freeze"])
        clock.late = 2 * 3600
        await watch._tick()
        self.assertIsNotNone(watch.snapshot()["last_freeze"])

    async def test_two_freezes_are_two_events(self) -> None:
        from mayedge.loop_watch import set_freeze_emitter

        clock = _Clock()
        events: list[dict[str, object]] = []
        set_freeze_emitter(events.append)
        watch = LoopWatch(clock)
        clock.wall_extra = 120
        await watch._tick()
        clock.wall_extra = 0
        await watch._tick()
        clock.wall_extra = 120
        await watch._tick()
        self.assertEqual(len(events), 2)
