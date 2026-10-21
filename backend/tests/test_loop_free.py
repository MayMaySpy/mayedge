"""Heavy reads run in a thread, so a slow loader does not stall the loop."""

from __future__ import annotations

import asyncio
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

from mayedge import db as store
from mayedge.api.routes.journal import NoteBody, get_summary, get_trips, put_note
from mayedge.api.routes.markets import (
    get_funding_average,
    get_funding_history,
    get_liquidation_summary,
    get_liquidations,
    get_open_interest,
)
from mayedge.api.routes.portfolio import get_portfolio_days, get_portfolio_history
from mayedge.config import settings
from mayedge.lighter.models import MarketMeta


def _slow(*_args: Any, **_kwargs: Any) -> list[Any]:
    time.sleep(0.3)
    return []


def _slow_none(*_args: Any, **_kwargs: Any) -> None:
    time.sleep(0.3)


async def assert_loop_free(awaitable: Any, max_gap_ms: float = 50) -> None:
    """Fail when a 10 ms ticker is late by more than max_gap_ms.

    A second thread sleeps the same 10 ms. A gap that shows up there too is the
    machine, not the loop, and does not count.
    """
    gaps: list[float] = []
    thread_gaps: list[float] = []
    stop = asyncio.Event()
    done = threading.Event()

    def probe() -> None:
        while not done.is_set():
            started = time.perf_counter()
            if done.wait(0.01):
                break
            thread_gaps.append((time.perf_counter() - started - 0.01) * 1000)

    async def ticker() -> None:
        loop = asyncio.get_running_loop()
        prev = loop.time()
        while not stop.is_set():
            await asyncio.sleep(0.01)
            now = loop.time()
            gaps.append((now - prev - 0.01) * 1000)
            prev = now

    probe_thread = threading.Thread(target=probe, daemon=True)
    probe_thread.start()
    task = asyncio.create_task(ticker())
    await asyncio.sleep(0.02)
    try:
        await awaitable
    finally:
        stop.set()
        done.set()
        await task
        probe_thread.join(timeout=1)
    floor = max(thread_gaps, default=0.0)
    late = [gap for gap in gaps if gap > max_gap_ms and gap > floor + max_gap_ms]
    if late:
        raise AssertionError(f"loop stalled {max(late):.0f} ms")


class LoopFreeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._td = TemporaryDirectory()
        self._patch = patch.object(settings, "db_path", str(Path(self._td.name) / "mayedge.db"))
        self._patch.start()
        store.close_db()
        store.init_db()
        self._meta = MarketMeta(1, "BTC", 2, 4, 0.001, 10.0, market_type="perp")

    def tearDown(self) -> None:
        store.close_db()
        self._patch.stop()
        self._td.cleanup()

    async def test_journal_trips_stay_off_the_loop(self) -> None:
        with patch("mayedge.api.routes.journal.journal_load_fills", side_effect=_slow):
            await assert_loop_free(get_trips())

    async def test_journal_summary_stays_off_the_loop(self) -> None:
        with patch("mayedge.api.routes.journal.journal_load_fills", side_effect=_slow):
            await assert_loop_free(get_summary())

    async def test_journal_note_stays_off_the_loop(self) -> None:
        with patch("mayedge.api.routes.journal.journal_put_note", side_effect=_slow_none):
            await assert_loop_free(put_note("1:a", NoteBody(note="n")))

    async def test_liquidations_stay_off_the_loop(self) -> None:
        with (
            patch("mayedge.api.routes.markets.gateway.recent_liquidations", return_value=[]),
            patch("mayedge.api.routes.markets.store.list_liquidations", side_effect=_slow),
        ):
            await assert_loop_free(get_liquidations())

    async def test_liquidation_summary_stays_off_the_loop(self) -> None:
        with patch("mayedge.api.routes.markets.store.summarize_liquidations", side_effect=_slow):
            await assert_loop_free(get_liquidation_summary())

    async def test_open_interest_stays_off_the_loop(self) -> None:
        with (
            patch("mayedge.api.routes.markets.gateway.get_market", return_value=self._meta),
            patch("mayedge.api.routes.markets.store.list_open_interest", side_effect=_slow),
        ):
            await assert_loop_free(get_open_interest("BTC"))

    async def test_funding_stays_off_the_loop(self) -> None:
        with (
            patch("mayedge.api.routes.markets.gateway.get_market", return_value=self._meta),
            patch("mayedge.api.routes.markets.store.list_funding", side_effect=_slow),
        ):
            await assert_loop_free(get_funding_history("BTC"))

    async def test_funding_average_stays_off_the_loop(self) -> None:
        with (
            patch("mayedge.api.routes.markets.gateway.get_market", return_value=self._meta),
            patch(
                "mayedge.api.routes.markets.store.funding_averages",
                side_effect=lambda *_a, **_k: _slow() or {"windows": [], "first_time": None},
            ),
        ):
            await assert_loop_free(get_funding_average("BTC"))

    async def test_portfolio_history_stays_off_the_loop(self) -> None:
        with patch("mayedge.api.routes.portfolio.portfolio_buckets", side_effect=_slow):
            await assert_loop_free(get_portfolio_history())

    async def test_portfolio_days_stay_off_the_loop(self) -> None:
        with patch("mayedge.api.routes.portfolio.portfolio_buckets", side_effect=_slow):
            await assert_loop_free(get_portfolio_days())
