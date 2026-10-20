"""A restart in the middle of a run neither doubles nor loses a Clip.

Each algo is started on a fake venue, drained, and restored from a fresh book
on the same SQLite file. While the desk is down the venue changes.
"""

from __future__ import annotations

import asyncio
import sys
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from mayedge import db as store
from mayedge.algos.chase import util
from mayedge.algos.chase.config import CHASE_COI_BASE, CHASE_COI_END, MIN_REQUOTE_MS
from mayedge.algos.grid import util as grid_util
from mayedge.algos.grid.book import ChaseGridBook
from mayedge.algos.grid.config import GRID_COI_BASE, GRID_COI_END
from mayedge.config import settings
from mayedge.feed_health import set_account_ws

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from chase_harness import (  # noqa: E402
    FakeGateway,
    FakeOrderService,
    boot_grid_job,
    boot_job,
    buy_params,
    make_execution,
    make_test_book,
    trade_print,
)
from venue_harness import FakeClock  # noqa: E402


class RestartTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._td = TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        db_path = patch.object(settings, "db_path", str(Path(self._td.name) / "mayedge.db"))
        db_path.start()
        self.addCleanup(db_path.stop)
        self.addCleanup(store.close_db)
        store.close_db()
        set_account_ws("live", broadcast=False)
        self.addCleanup(lambda: set_account_ws("down", broadcast=False))

    async def test_chase_counts_a_downtime_fill_once_and_does_not_reuse_the_clip(self) -> None:
        gateway = FakeGateway()
        orders = FakeOrderService()
        clock = FakeClock()
        with patch.object(util, "now_ms", clock):
            boot = boot_job(
                clock=clock,
                params=buy_params(qty=D("10"), display_qty=D("1")),
                gateway=gateway,
                orders=orders,
            )
            await boot.job._evaluate()
            coi = int(orders.creates[0]["client_order_index"])
            oid = int(orders.creates[0]["order_index"])
            self.assertGreaterEqual(coi, CHASE_COI_BASE)
            self.assertLess(coi, CHASE_COI_END)
            orders.set_remaining(coi, "0.4", filled="0.6")
            boot.clock.advance(MIN_REQUOTE_MS + 1)
            await boot.job._evaluate()
            self.assertEqual(boot.job.state.filled, D("0.6"))
            await boot.book.drain_for_shutdown()
            # The rest of the Clip filled as the cancel landed. One trade, one id.
            orders.trades_response = [
                trade_print(
                    market_index=1,
                    size="1",
                    price="99.96",
                    trade_id=99,
                    bid_client_id=coi,
                    bid_id=oid,
                )
            ]
            store.close_db()
            fresh = make_test_book(gateway, orders)
            await fresh.restore()
            again: object | None = None
            try:
                self.assertEqual(list(fresh._jobs), [boot.algo_id])
                job = fresh._jobs[boot.algo_id]
                self.assertEqual(job.state.filled, D("1"))
                self.assertEqual(job.state.remaining, D("9"))
                live = [o for o in orders.open_orders if int(o["market_index"]) == 1]
                self.assertEqual(len(live), 1)
                new_coi = int(live[0]["client_order_index"])
                self.assertNotEqual(new_coi, coi)
                self.assertGreaterEqual(new_coi, CHASE_COI_BASE)
                self.assertLess(new_coi, CHASE_COI_END)
                # The same trade on a second restore must not move the size again.
                orders.trades_response = [
                    trade_print(
                        market_index=1,
                        size="1",
                        price="99.96",
                        trade_id=99,
                        bid_client_id=coi,
                        bid_id=oid,
                    )
                ]
                await job.drain_for_shutdown()
                store.close_db()
                again = make_test_book(gateway, orders)
                await again.restore()
                restored = again._jobs[boot.algo_id]
                self.assertEqual(restored.state.filled, D("1"))
                self.assertEqual(restored.state.remaining, D("9"))
            finally:
                await _stop_books(fresh)
                if again is not None:
                    await _stop_books(again)

    async def test_grid_counts_a_downtime_fill_once_and_keeps_its_band(self) -> None:
        gateway = FakeGateway()
        orders = FakeOrderService()
        clock = FakeClock()
        with (
            patch.object(util, "now_ms", clock),
            patch.object(grid_util, "now_ms", clock),
        ):
            boot = boot_grid_job(gateway=gateway, orders=orders, clock=clock)
            await boot.job._evaluate()
            buys = [c for c in orders.creates if c["side"] == "buy" and not c.get("reduce_only")]
            self.assertEqual(len(buys), 1)
            coi = int(buys[0]["client_order_index"])
            oid = int(buys[0]["order_index"])
            self.assertGreaterEqual(coi, GRID_COI_BASE)
            self.assertLess(coi, GRID_COI_END)
            orders.set_remaining(coi, "0.4", filled="0.6")
            clock.advance(MIN_REQUOTE_MS + 1)
            await boot.job._evaluate()
            await boot.book.drain_for_shutdown()
            orders.trades_response = [
                trade_print(
                    market_index=1,
                    size="1",
                    price="99.96",
                    trade_id=99,
                    bid_client_id=coi,
                    bid_id=oid,
                )
            ]
            store.close_db()
            again: object | None = None
            fresh = ChaseGridBook(
                execution=lambda: make_execution(gateway, orders),
                broadcast=gateway.broadcast,
            )
            await fresh.restore()
            try:
                job = fresh._jobs[boot.algo_id]
                clip = job.state.ledger.find_clip(client_order_index=coi)
                assert clip is not None
                self.assertEqual(clip.filled, D("1"))
                cois = [int(o["client_order_index"]) for o in orders.open_orders]
                self.assertEqual(len(cois), len(set(cois)))
                for live in cois:
                    self.assertGreaterEqual(live, GRID_COI_BASE)
                    self.assertLess(live, GRID_COI_END)
                    self.assertNotEqual(live, coi)
                await job.drain_for_shutdown()
                store.close_db()
                again = ChaseGridBook(
                    execution=lambda: make_execution(gateway, orders),
                    broadcast=gateway.broadcast,
                )
                await again.restore()
                clip = again._jobs[boot.algo_id].state.ledger.find_clip(client_order_index=coi)
                assert clip is not None
                self.assertEqual(clip.filled, D("1"))
            finally:
                await _stop_books(fresh)
                if again is not None:
                    await _stop_books(again)


async def _stop_books(book: object) -> None:
    jobs = getattr(book, "_jobs", {})
    for job in list(jobs.values()):
        task = getattr(job, "_task", None)
        stop = getattr(job, "_stop", None)
        if stop is not None:
            stop.set()
        wake = getattr(job, "_wake", None)
        if wake is not None:
            wake.set()
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
