"""Scan boards yield between markets so the math does not stall the loop."""

from __future__ import annotations

import asyncio
import time
import unittest
from collections import deque
from collections.abc import Awaitable
from unittest.mock import patch

from mayedge.alerts import MarketSnapshot
from mayedge.lighter.gateway import LighterGateway
from mayedge.lighter.models import MarketMeta


def _snap(ts: float) -> MarketSnapshot:
    return MarketSnapshot(
        ts=ts,
        mark=100.0,
        last=100.0,
        index=100.0,
        mid=100.0,
        bid=100.0,
        ask=100.01,
        oi=1.0,
        vol_quote=2_000_000.0,
        funding=0.01,
        premium=0.1,
        day_high=110.0,
        day_low=90.0,
    )


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


class ScanLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_scan_math_lets_the_loop_run_between_markets(self) -> None:
        gw = LighterGateway()
        det = gw._alerts
        now = time.time()
        for mi in range(6):
            det._snapshots[mi] = deque([_snap(now)], maxlen=400)
            det._symbols[mi] = f"M{mi}"

        def burn(*_args: object, **_kwargs: object) -> float:
            end = time.perf_counter() + 0.015
            n = 0
            while time.perf_counter() < end:
                n += 1
            return 1.0

        with patch.object(det._level, "z", burn):
            gap = await _max_loop_gap_ms(gw._publish_scan_boards())
        # Activity calls z twice on one market before it yields. Six markets
        # with no yield between them would be many times this.
        self.assertLess(gap, 50.0)

    async def test_market_stats_lets_the_loop_run_between_markets(self) -> None:
        gw = LighterGateway()
        for mi in range(6):
            gw._markets[mi] = MarketMeta(
                market_index=mi,
                symbol=f"M{mi}",
                price_decimals=2,
                size_decimals=4,
                min_base_amount=0.0,
                min_quote_amount=0.0,
            )

        def burn(_meta: object) -> None:
            end = time.perf_counter() + 0.015
            n = 0
            while time.perf_counter() < end:
                n += 1

        msg = {"market_stats": {str(mi): {"market_id": mi, "mark_price": "100"} for mi in range(6)}}
        with patch.object(gw._alerts, "on_market_stats", burn):
            gap = await _max_loop_gap_ms(gw.apply_market_stats(msg))
        self.assertLess(gap, 40.0)
