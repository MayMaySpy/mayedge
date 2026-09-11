"""Chase-grid runner tests (fake clock / venue)."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from typing import cast
from unittest import IsolatedAsyncioTestCase

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from mayedge.algos.grid.job import GridRunner

from chase_harness import (  # noqa: E402
    FakeGateway,
    boot_grid_job,
    isolated_db,
    patch_grid,
)

D = Decimal


class IsolatedGridTestCase(IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._db = isolated_db()
        cls._db.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._db.__exit__(None, None, None)


class GridRunnerDustTests(IsolatedGridTestCase):
    async def test_partial_below_min_qty_replaces_chase_clip(self) -> None:
        """Sub-min chase leftover is cancelled; a full clip rests immediately."""
        gateway = FakeGateway()
        assert gateway.market is not None
        gateway.market.min_base_amount = 0.5
        boot = boot_grid_job(gateway=gateway)
        with patch_grid(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            chase_buys = [
                c
                for c in boot.orders.creates
                if c["side"] == "buy" and not c["reduce_only"]
            ]
            self.assertEqual(len(chase_buys), 1)
            first_coi = chase_buys[0]["client_order_index"]
            boot.orders.set_remaining(first_coi, "0.4", filled="0.6")
            await boot.job._evaluate()

        chase_buys = [
            c for c in boot.orders.creates if c["side"] == "buy" and not c["reduce_only"]
        ]
        self.assertEqual(len(chase_buys), 2)
        self.assertGreaterEqual(len(boot.orders.cancels), 1)
        self.assertEqual(boot.orders.modifies, [])
        self.assertNotEqual(chase_buys[1]["client_order_index"], first_coi)
        self.assertEqual(chase_buys[1]["size"], "1")
        job = cast(GridRunner, boot.job)
        live = job._chase_clip("buy")
        assert live is not None
        self.assertNotEqual(live.client_order_index, first_coi)
        self.assertEqual(live.qty, D("1"))
        self.assertEqual(live.remaining, D("1"))
        rt = job.state.runtime
        self.assertEqual(rt.inventory, D("0.6"))
        self.assertEqual(len(rt.lots), 1)
        self.assertEqual(rt.lots[0].qty, D("0.6"))
        self.assertIsNone(job._chase_clip("sell"))
