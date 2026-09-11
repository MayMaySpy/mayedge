from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock

from mayedge.api.ws import _FANOUT_MAX, BroadcastFanout


class BroadcastFanoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_drains_messages_in_order(self) -> None:
        sent: list[dict] = []

        async def capture(msg: dict) -> None:
            sent.append(msg)

        fanout = BroadcastFanout(capture)
        fanout.start()
        fanout.push({"type": "a", "n": 1})
        fanout.push({"type": "b", "n": 2})
        fanout.push({"type": "c", "n": 3})
        await asyncio.sleep(0.05)
        await fanout.stop()
        self.assertEqual(
            sent,
            [
                {"type": "a", "n": 1},
                {"type": "b", "n": 2},
                {"type": "c", "n": 3},
            ],
        )

    async def test_uses_single_broadcast_per_message(self) -> None:
        broadcast = AsyncMock()
        fanout = BroadcastFanout(broadcast)
        fanout.start()
        fanout.push({"type": "tick"})
        await asyncio.sleep(0.05)
        await fanout.stop()
        broadcast.assert_awaited_once_with({"type": "tick"})

    async def test_coalesces_market_stats_by_index(self) -> None:
        sent: list[dict] = []

        async def capture(msg: dict) -> None:
            sent.append(msg)

        fanout = BroadcastFanout(capture)
        fanout.start()
        fanout.push({"type": "market_stats", "markets": [{"market_index": 1, "mark_price": 1}]})
        fanout.push({"type": "market_stats", "markets": [{"market_index": 2, "mark_price": 2}]})
        fanout.push({"type": "market_stats", "markets": [{"market_index": 1, "mark_price": 3}]})
        await asyncio.sleep(0.05)
        await fanout.stop()
        self.assertEqual(len(sent), 1)
        by_idx = {row["market_index"]: row["mark_price"] for row in sent[0]["markets"]}
        self.assertEqual(by_idx, {1: 3, 2: 2})

    async def test_replaces_pending_account(self) -> None:
        sent: list[dict] = []

        async def capture(msg: dict) -> None:
            sent.append(msg)

        fanout = BroadcastFanout(capture)
        fanout.start()
        fanout.push({"type": "account", "n": 1})
        fanout.push({"type": "account", "n": 2})
        await asyncio.sleep(0.05)
        await fanout.stop()
        self.assertEqual(sent, [{"type": "account", "n": 2}])

    async def test_overflow_drops_instead_of_growing(self) -> None:
        gate = asyncio.Event()

        async def slow(_msg: dict) -> None:
            await gate.wait()

        fanout = BroadcastFanout(slow)
        fanout.start()
        for i in range(_FANOUT_MAX + 200):
            fanout.push({"type": "order_book_delta", "n": i})
        q = fanout._queue
        assert q is not None
        self.assertLessEqual(q.qsize(), _FANOUT_MAX + 8)
        self.assertGreater(fanout.dropped, 0)
        gate.set()
        await fanout.stop()


if __name__ == "__main__":
    unittest.main()
