"""A restart in the middle of a run neither doubles nor loses a Clip.

Each algo is started on a fake venue, drained, and restored from a fresh book
on the same SQLite file. While the desk is down the venue changes.
"""

from __future__ import annotations

import asyncio
import contextlib
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
from mayedge.algos.ladder.book import LadderBook
from mayedge.algos.ladder.config import LADDER_COI_BASE, LADDER_COI_END, MIN_PLACE_GAP_MS
from mayedge.algos.ladder.plan import LadderParams, build_rungs
from mayedge.algos.planner.book import PlannerBook
from mayedge.algos.trail.book import TrailBook
from mayedge.algos.trail.config import MIN_GAP_MS
from mayedge.algos.twap.book import AdvancedTwapBook
from mayedge.algos.twap.plan import TWAP_COI_BASE, TWAP_COI_END, AdvancedTwapParams
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
from planner_harness import MI, FakeVenue  # noqa: E402
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

    async def test_ladder_counts_a_downtime_fill_once_and_keeps_its_band(self) -> None:
        """Two rungs rest. One is filled while down, the other cancelled. Neither COI comes back."""
        clock = FakeClock()
        params = LadderParams(
            side="buy",
            qty=D("4"),
            price_from=D("100"),
            price_to=D("97"),
            rungs=4,
            window=2,
        )
        params.rung_list = build_rungs(
            side="buy",
            qty=D("4"),
            price_from=D("100"),
            price_to=D("97"),
            rungs=4,
            tick=D("0.01"),
            qty_step=D("0.1"),
            min_qty=D("0.1"),
        )
        gateway = FakeGateway()
        orders = FakeOrderService()
        book = LadderBook(
            execution=lambda: make_execution(gateway, orders),
            broadcast=gateway.broadcast,
        )
        again: object | None = None
        with (
            patch("mayedge.algos.common.now_ms", clock),
            patch.object(util, "now_ms", clock),
        ):
            await book.start(market_index=1, params=params)
            job = next(iter(book._jobs.values()))
            await _quiet(job)
            # The first look places one rung, then waits out the place gap.
            clock.advance(MIN_PLACE_GAP_MS + 1)
            await job._evaluate()
            live = job.state.ledger.live_clips()
            self.assertEqual(len(live), 2)
            filled_clip, cancelled_clip = live[0], live[1]
            self.assertEqual(filled_clip.qty, D("1"))
            orders.set_remaining(filled_clip.client_order_index, "0.4", filled="0.6")
            await job._evaluate()
            self.assertEqual(filled_clip.filled, D("0.6"))
            old = {filled_clip.client_order_index, cancelled_clip.client_order_index}
            await book.drain_for_shutdown()
            orders.remove_by_coi(cancelled_clip.client_order_index)
            orders.trades_response = [
                trade_print(
                    market_index=1,
                    size="1",
                    price="100",
                    trade_id=71,
                    bid_client_id=filled_clip.client_order_index,
                    bid_id=filled_clip.order_index or 0,
                )
            ]
            store.close_db()
            fresh = LadderBook(
                execution=lambda: make_execution(gateway, orders),
                broadcast=gateway.broadcast,
            )
            await fresh.restore()
            try:
                restored = fresh._jobs[job.state.algo_id]
                clip = restored.state.ledger.find_clip(
                    client_order_index=filled_clip.client_order_index
                )
                other = restored.state.ledger.find_clip(
                    client_order_index=cancelled_clip.client_order_index
                )
                assert clip is not None and other is not None
                self.assertEqual(clip.filled, D("1"))
                self.assertEqual(other.filled, D("0"))
                self.assertEqual(restored.state.filled, D("1"))
                self.assertEqual(restored.state.remaining, D("3"))
                cois = [int(o["client_order_index"]) for o in orders.open_orders]
                self.assertEqual(len(cois), len(set(cois)))
                self.assertTrue(cois)
                for live_coi in cois:
                    self.assertGreaterEqual(live_coi, LADDER_COI_BASE)
                    self.assertLess(live_coi, LADDER_COI_END)
                    self.assertNotIn(live_coi, old)
                await restored.drain_for_shutdown()
                store.close_db()
                again = LadderBook(
                    execution=lambda: make_execution(gateway, orders),
                    broadcast=gateway.broadcast,
                )
                await again.restore()
                second = again._jobs[job.state.algo_id]
                self.assertEqual(second.state.filled, D("1"))
                self.assertEqual(second.state.remaining, D("3"))
            finally:
                await _stop_books(fresh)
                if again is not None:
                    await _stop_books(again)

    async def test_twap_counts_a_downtime_fill_once_and_keeps_its_band(self) -> None:
        """A resting slice filled while down is counted once. The next slice is a new COI."""
        clock = FakeClock()
        gateway = FakeGateway()
        orders = FakeOrderService()
        params = AdvancedTwapParams(
            side="buy",
            qty=D("9"),
            duration_seconds=60,
            frequency_seconds=30,
            style="passive",
            randomize=False,
        )
        book = AdvancedTwapBook(
            execution=lambda: make_execution(gateway, orders),
            broadcast=gateway.broadcast,
        )
        again: object | None = None
        with patch("mayedge.algos.twap.job.now_ms", clock):
            await book.start(market_index=1, params=params)
            job = next(iter(book._jobs.values()))
            await _quiet(job)
            clip = job.ledger.working()
            assert clip is not None
            self.assertEqual(clip.qty, D("3"))
            old = clip.client_order_index
            self.assertGreaterEqual(old, TWAP_COI_BASE)
            self.assertLess(old, TWAP_COI_END)
            await book.drain_for_shutdown()
            orders.trades_response = [
                trade_print(
                    market_index=1,
                    size="3",
                    price="100",
                    trade_id=72,
                    bid_client_id=old,
                    bid_id=clip.order_index or 0,
                )
            ]
            store.close_db()
            fresh = AdvancedTwapBook(
                execution=lambda: make_execution(gateway, orders),
                broadcast=gateway.broadcast,
            )
            await fresh.restore()
            try:
                restored = fresh._jobs[job.algo_id]
                done = restored.ledger.find_clip(client_order_index=old)
                assert done is not None
                self.assertEqual(done.filled, D("3"))
                self.assertEqual(restored.filled, D("3"))
                self.assertEqual(restored.remaining, D("6"))
                cois = [int(o["client_order_index"]) for o in orders.open_orders]
                self.assertEqual(len(cois), len(set(cois)))
                self.assertTrue(cois)
                for live_coi in cois:
                    self.assertGreaterEqual(live_coi, TWAP_COI_BASE)
                    self.assertLess(live_coi, TWAP_COI_END)
                    self.assertNotEqual(live_coi, old)
                await restored.drain_for_shutdown()
                store.close_db()
                again = AdvancedTwapBook(
                    execution=lambda: make_execution(gateway, orders),
                    broadcast=gateway.broadcast,
                )
                await again.restore()
                second = again._jobs[job.algo_id]
                self.assertEqual(second.filled, D("3"))
                self.assertEqual(second.remaining, D("6"))
            finally:
                await _stop_books(fresh)
                if again is not None:
                    await _stop_books(again)

    async def test_planner_adopts_its_stop_and_counts_a_target_fill_once(self) -> None:
        """The stop stays. One target fills while down, another is cancelled, and neither is re-sent."""
        clock = FakeClock()
        venue = FakeVenue()
        book = PlannerBook(execution=lambda: venue.execution(), broadcast=lambda _p: None)
        again: object | None = None
        with patch.object(util, "now_ms", clock):
            await book.start_from_body(
                {
                    "market_index": MI,
                    "mode": "enter",
                    "side": "buy",
                    "stop": "95",
                    "targets": [
                        {"kind": "r", "value": "1", "pct": "50", "order": "trigger"},
                        {"kind": "r", "value": "2", "pct": "50", "order": "trigger"},
                    ],
                    "entry_type": "limit",
                    "entry_price": "100",
                    "size": "2",
                }
            )
            job = next(iter(book._jobs.values()))
            await job._halt()
            entry = venue.sent("limit")[0]
            venue.fill(int(entry["client_order_index"]), "2", price="100")
            await job._evaluate()
            self.assertEqual(job.state.phase, "managing")
            stop = venue.sent("trigger_sl")[0]
            targets = venue.sent("trigger_tp")
            self.assertEqual(len(targets), 2)
            stop_coi = int(stop["client_order_index"])
            trigger = job.state.stop_trigger
            self.assertEqual(trigger, D("95"))
            filled_coi = int(targets[0]["client_order_index"])
            cancelled_coi = int(targets[1]["client_order_index"])
            await book.drain_for_shutdown()
            self.assertIn(stop_coi, venue.orders)
            venue.fill(filled_coi, "1")
            del venue.orders[cancelled_coi]
            stops_sent = len(venue.sent("trigger_sl"))
            targets_sent = len(venue.sent("trigger_tp"))
            store.close_db()
            fresh = PlannerBook(execution=lambda: venue.execution(), broadcast=lambda _p: None)
            await fresh.restore()
            try:
                restored = fresh._jobs[job.state.algo_id]
                self.assertEqual(restored.state.stop_trigger, trigger)
                self.assertEqual(len(venue.sent("trigger_sl")), stops_sent)
                self.assertEqual(len(venue.sent("trigger_tp")), targets_sent)
                stops = [o for o in venue.orders.values() if o["order_type"] == "stop-loss"]
                self.assertEqual([int(o["client_order_index"]) for o in stops], [stop_coi])
                filled = restored.state.ledger.find_clip(client_order_index=filled_coi)
                cancelled = restored.state.ledger.find_clip(client_order_index=cancelled_coi)
                assert filled is not None and cancelled is not None
                self.assertEqual(filled.filled, filled.qty)
                self.assertEqual(filled.status, "filled")
                self.assertNotEqual(cancelled.status, "filled")
                self.assertNotIn(cancelled_coi, venue.orders)
                cois = [int(o["client_order_index"]) for o in venue.orders.values()]
                self.assertEqual(len(cois), len(set(cois)))
                await _stop_books(fresh)
                store.close_db()
                again = PlannerBook(execution=lambda: venue.execution(), broadcast=lambda _p: None)
                await again.restore()
                second = again._jobs[job.state.algo_id]
                filled_again = second.state.ledger.find_clip(client_order_index=filled_coi)
                assert filled_again is not None
                self.assertEqual(filled_again.filled, filled.qty)
                self.assertEqual(second.state.stop_trigger, trigger)
                self.assertEqual(len(venue.sent("trigger_sl")), stops_sent)
            finally:
                await _stop_books(fresh)
                if again is not None:
                    await _stop_books(again)

    async def test_trail_adopts_its_stop_and_does_not_move_the_trigger_back(self) -> None:
        """A Trail Stop left on the venue is the same order after a restart, trigger included."""
        clock = FakeClock()
        venue = FakeVenue()
        venue.position = D("2")
        venue.entry = D("100")
        book = TrailBook(execution=lambda: venue.execution(), broadcast=lambda _p: None)
        again: object | None = None
        with patch.object(util, "now_ms", clock):
            await book.start_from_body(
                {"market_index": MI, "kind": "stop", "distance": "1", "distance_kind": "price"}
            )
            job = next(iter(book._jobs.values()))
            await job._halt()
            clock.advance(MIN_GAP_MS)
            venue.set_mark("103")
            await job._evaluate()
            self.assertEqual(job.state.venue_trigger, D("102"))
            self.assertEqual(job.state.point.best, D("103"))
            stop_coi = int(venue.sent("trigger_sl")[0]["client_order_index"])
            await book.drain_for_shutdown()
            self.assertIn(stop_coi, venue.orders)
            venue.set_mark("101")
            sent = len(venue.sent("trigger_sl"))
            amends = len(venue.sent("amend"))
            store.close_db()
            fresh = TrailBook(execution=lambda: venue.execution(), broadcast=lambda _p: None)
            await fresh.restore()
            try:
                restored = fresh._jobs[job.state.algo_id]
                self.assertEqual(restored.state.venue_trigger, D("102"))
                self.assertEqual(restored.state.point.best, D("103"))
                self.assertEqual(restored.state.point.trigger, D("102"))
                self.assertEqual(len(venue.sent("trigger_sl")), sent)
                self.assertEqual(len(venue.sent("amend")), amends)
                stops = [o for o in venue.orders.values() if o["order_type"] == "stop-loss"]
                self.assertEqual([int(o["client_order_index"]) for o in stops], [stop_coi])
                await _stop_books(fresh)
                store.close_db()
                again = TrailBook(execution=lambda: venue.execution(), broadcast=lambda _p: None)
                await again.restore()
                second = again._jobs[job.state.algo_id]
                self.assertEqual(second.state.venue_trigger, D("102"))
                self.assertEqual(second.state.point.trigger, D("102"))
                self.assertEqual(len(venue.sent("trigger_sl")), sent)
                self.assertEqual(len(venue.sent("amend")), amends)
            finally:
                await _stop_books(fresh)
                if again is not None:
                    await _stop_books(again)


async def _quiet(job: object) -> None:
    """Stop the run loop without marking the job shut down."""
    task = getattr(job, "_task", None)
    if task is not None and not task.done():
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def _stop_books(book: object) -> None:
    jobs = getattr(book, "_jobs", {})
    for job in list(jobs.values()):
        task = getattr(job, "_task", None)
        stop = getattr(job, "_stop", None)
        if stop is not None:
            stop.set()
        gate = getattr(job, "_run_gate", None)
        if gate is not None:
            gate.set()
        wake = getattr(job, "_wake", None)
        if wake is not None:
            wake.set()
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
