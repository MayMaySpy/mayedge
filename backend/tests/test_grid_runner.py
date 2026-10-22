"""Chase-grid runner tests (fake clock / venue)."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from unittest import IsolatedAsyncioTestCase

from mayedge.algos.chase.state import ChaseStatus
from mayedge.algos.grid.config import GRID_COI_BASE
from mayedge.algos.grid.decide import GridAction, Lot, SideQuote
from mayedge.algos.grid.job import GridRunner

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

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
                c for c in boot.orders.creates if c["side"] == "buy" and not c["reduce_only"]
            ]
            self.assertEqual(len(chase_buys), 1)
            first_coi = chase_buys[0]["client_order_index"]
            boot.orders.set_remaining(first_coi, "0.4", filled="0.6")
            boot.orders.positions = [{"market_index": 1, "size": "0.6", "entry_price": "100"}]
            await boot.job._evaluate()

        chase_buys = [c for c in boot.orders.creates if c["side"] == "buy" and not c["reduce_only"]]
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


def _chase_sells(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [o for o in orders if o.get("side") == "sell" and not o.get("reduce_only")]


class GridRunnerDeadChildTests(IsolatedGridTestCase):
    async def test_long_inventory_cancels_venue_chase_sells_dropped_from_ledger(self) -> None:
        """Chase sells closed in the ledger but still on venue must not stay put."""
        boot = boot_grid_job()
        job = cast(GridRunner, boot.job)
        with patch_grid(boot.clock, boot.gateway, boot.orders):
            await job._evaluate()
            sell = job._chase_clip("sell")
            assert sell is not None
            dropped_coi = sell.client_order_index
            job.state.ledger.close_missing(sell, canceling=True, now=boot.clock())
            self.assertIsNotNone(boot.orders.find_by_coi(dropped_coi))

            orphan_coi = GRID_COI_BASE + 99
            boot.orders.open_orders.append(
                {
                    "market_index": 1,
                    "order_index": 999,
                    "client_order_index": orphan_coi,
                    "side": "sell",
                    "price": "100.50",
                    "initial": "1",
                    "remaining": "1",
                    "filled": "0",
                    "size": "1",
                }
            )

            job.state.runtime.inventory = D("2")
            job.state.runtime.lots = [
                Lot("a", D("100"), D("2"), D("100"), "long", D("100.40"), opened_at=1)
            ]
            boot.orders.positions = [{"market_index": 1, "size": "2", "entry_price": "100"}]
            await job._evaluate()

        self.assertIsNone(boot.orders.find_by_coi(dropped_coi))
        self.assertIsNone(boot.orders.find_by_coi(orphan_coi))
        self.assertEqual(_chase_sells(boot.orders.open_orders), [])
        self.assertIsNone(job._chase_clip("sell"))

    async def test_requote_does_not_stack_a_chase_sell_left_on_venue(self) -> None:
        """A ledger-dropped chase sell is pulled before a replacement rests."""
        boot = boot_grid_job()
        job = cast(GridRunner, boot.job)
        with patch_grid(boot.clock, boot.gateway, boot.orders):
            await job._evaluate()
            sell = job._chase_clip("sell")
            assert sell is not None
            dropped_coi = sell.client_order_index
            job.state.ledger.close_missing(sell, canceling=True, now=boot.clock())
            await job._evaluate()

        self.assertIsNone(boot.orders.find_by_coi(dropped_coi))
        live = job._chase_clip("sell")
        assert live is not None
        self.assertNotEqual(live.client_order_index, dropped_coi)
        self.assertEqual(len(_chase_sells(boot.orders.open_orders)), 1)


class GridRunnerRestoreTests(IsolatedGridTestCase):
    async def test_error_restore_unproven_auto_resumes(self) -> None:
        """A grid restored in a recoverable error quotes again, as chase and ladder do."""
        boot = boot_grid_job()
        job = cast(GridRunner, boot.job)
        with patch_grid(boot.clock, boot.gateway, boot.orders):
            await job._evaluate()
            row = {
                **job.snapshot(),
                **job.state.ledger.to_persist(),
                "status": "error",
                "error": "unproven_missing_clip",
            }
            job.hydrate_from_row(row)
            await job.resume()
            self.assertEqual(job.state.status, ChaseStatus.RUNNING)
            self.assertIsNone(job.state.error)
            self.assertIsNotNone(job._task)
            await job.stop()
        self.assertEqual(job.state.status, ChaseStatus.STOPPED)


class GridRunnerInventoryTests(IsolatedGridTestCase):
    async def test_flat_venue_clears_phantom_inventory(self) -> None:
        """Inv follows the account position, not leftover clip bookkeeping."""
        boot = boot_grid_job()
        job = cast(GridRunner, boot.job)
        with patch_grid(boot.clock, boot.gateway, boot.orders):
            await job._evaluate()
            job.state.runtime.inventory = D("-3.6")
            job.state.runtime.inventory_vwap = D("100")
            job.state.runtime.lots = [
                Lot("ghost", D("100"), D("3.6"), D("100"), "short", D("99.60"), opened_at=1)
            ]
            await job._evaluate()

        self.assertEqual(job.state.runtime.inventory, D("0"))
        self.assertIsNone(job.state.runtime.inventory_vwap)
        self.assertEqual(job.state.runtime.lots, [])
        snap = job.snapshot()
        self.assertEqual(snap["inventory"], "0")


class GridModifyRejectTests(IsolatedGridTestCase):
    async def _live_buy(self, boot: Any) -> Any:
        job = cast(GridRunner, boot.job)
        await job._evaluate()
        clip = job._chase_clip("buy")
        self.assertIsNotNone(clip)
        return clip

    async def test_modify_nonce_is_not_a_quiet_cross(self) -> None:
        """A nonce error whose headers say POST must reach the tx handler."""
        boot = boot_grid_job()
        job = cast(GridRunner, boot.job)
        quote = SideQuote(GridAction.REST, price=D("99.5"), qty=D("1"))
        with patch_grid(boot.clock, boot.gateway, boot.orders):
            clip = await self._live_buy(boot)
            boot.orders.modify_error = ValueError(
                "HTTP response headers: Access-Control-Allow-Methods: GET, POST, cross-origin\n"
                "HTTP response body: code=21104 message='invalid nonce'"
            )
            with self.assertLogs("mayedge.algos.chase.place", level="WARNING") as logs:
                await job._modify_side(clip, quote)
        self.assertEqual(job._backoff_reason, "invalid_nonce")
        self.assertTrue(any("invalid nonce" in line for line in logs.output))
        self.assertEqual(boot.orders.cancels, [])

    async def test_modify_header_noise_is_logged(self) -> None:
        boot = boot_grid_job()
        job = cast(GridRunner, boot.job)
        quote = SideQuote(GridAction.REST, price=D("99.5"), qty=D("1"))
        with patch_grid(boot.clock, boot.gateway, boot.orders):
            clip = await self._live_buy(boot)
            boot.orders.modify_error = ValueError(
                "HTTP response headers: Access-Control-Allow-Methods: GET, POST, cross-origin"
            )
            with self.assertLogs("mayedge.algos.grid.job", level="WARNING") as logs:
                await job._modify_side(clip, quote)
        self.assertIsNone(job._backoff_reason)
        self.assertTrue(any("grid modify failed" in line for line in logs.output))
