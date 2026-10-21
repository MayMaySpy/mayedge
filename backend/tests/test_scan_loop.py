"""Scan boards are built off the event loop."""

from __future__ import annotations

import time
import unittest
from unittest.mock import patch

try:
    from test_loop_free import assert_loop_free
except ImportError:  # discover -s tests, or python -m unittest tests.test_scan_loop
    from tests.test_loop_free import assert_loop_free

from mayedge.lighter.gateway import LighterGateway


class ScanLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_building_the_boards_does_not_stall_the_loop(self) -> None:
        gw = LighterGateway()

        def slow() -> list[tuple[str, list[dict[str, object]], str]]:
            time.sleep(0.3)
            return [("scan_activity", [], "[]")]

        with patch.object(gw, "_scan_payloads", slow):
            await assert_loop_free(gw._publish_scan_boards())
