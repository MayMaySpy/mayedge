"""Alive marks, and the Down gap a boot reports from them."""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

try:
    from test_loop_free import assert_loop_free
except ImportError:  # discover -s tests, or python -m unittest tests.test_alive
    from tests.test_loop_free import assert_loop_free

from mayedge import db as store
from mayedge.alive import last_down, mark_clean, mark_once, note_boot, run_alive, write_alive
from mayedge.config import settings

_TWO_H = 2 * 60 * 60 * 1000


class AliveTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._dir = TemporaryDirectory()
        self._old = settings.db_path
        settings.db_path = str(Path(self._dir.name) / "mayedge.db")
        store.close_db()

    def tearDown(self) -> None:
        note_boot(0, 60)
        store.close_db()
        settings.db_path = self._old
        self._dir.cleanup()

    async def test_marks_are_written_every_30s(self) -> None:
        clock = {"ms": 1_000}
        stamps: list[int] = []

        def now() -> int:
            stamps.append(clock["ms"])
            return clock["ms"]

        async def sleep(seconds: float) -> None:
            clock["ms"] += int(seconds * 1000)
            if len(stamps) >= 3:
                raise asyncio.CancelledError

        with self.assertRaises(asyncio.CancelledError):
            await run_alive(sleep, now)
        self.assertEqual(stamps, [1_000, 31_000, 61_000])
        self.assertEqual(last_written(), 61_000)

    async def test_a_boot_two_hours_later_is_not_a_clean_stop(self) -> None:
        write_alive(1_000)
        gap = note_boot(1_000 + _TWO_H, 60)
        self.assertIsNotNone(gap)
        assert gap is not None
        self.assertEqual(gap["to"], 1_000 + _TWO_H)
        self.assertEqual(int(gap["to"]) - int(gap["from"]), _TWO_H)
        self.assertFalse(gap["clean"])
        self.assertEqual(last_down(), gap)

    async def test_a_shutdown_then_a_boot_is_a_clean_stop(self) -> None:
        write_alive(5_000)
        mark_clean(5_000)
        gap = note_boot(5_000 + _TWO_H, 60)
        assert gap is not None
        self.assertTrue(gap["clean"])

    async def test_a_short_gap_and_a_fresh_database_report_nothing(self) -> None:
        self.assertIsNone(note_boot(10_000, 60))
        self.assertIsNone(last_down())
        write_alive(10_000)
        self.assertIsNone(note_boot(10_000 + 30_000, 60))
        self.assertIsNone(last_down())

    async def test_the_mark_does_not_run_on_the_loop(self) -> None:
        await assert_loop_free(_slow_mark())


async def _slow_mark() -> None:
    import time
    from unittest.mock import patch

    def slow(now_ms: int) -> None:
        time.sleep(0.3)
        write_alive(now_ms)

    with patch("mayedge.alive.write_alive", slow):
        await mark_once(1)


def last_written() -> int | None:
    from mayedge.db import _connect, _lock

    with _lock:
        conn = _connect()
        row = conn.execute("SELECT value FROM meta WHERE key = 'alive_at'").fetchone()
    return None if row is None else int(row["value"])
