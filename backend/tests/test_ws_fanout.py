from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock

from mayedge.api.ws import BroadcastFanout


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
        self.assertEqual(sent, [
            {"type": "a", "n": 1},
            {"type": "b", "n": 2},
            {"type": "c", "n": 3},
        ])

    async def test_uses_single_broadcast_per_message(self) -> None:
        broadcast = AsyncMock()
        fanout = BroadcastFanout(broadcast)
        fanout.start()
        fanout.push({"type": "tick"})
        await asyncio.sleep(0.05)
        await fanout.stop()
        broadcast.assert_awaited_once_with({"type": "tick"})


if __name__ == "__main__":
    unittest.main()
