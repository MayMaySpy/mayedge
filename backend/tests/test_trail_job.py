"""Trail job against a fake venue. Rule ids are docs/trail-rules.md."""

from __future__ import annotations

import sys
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from mayedge import db as store
from mayedge.algos.chase.state import ChaseStatus
from mayedge.algos.planner import venue as planner_venue
from mayedge.algos.trail.book import TrailBook
from mayedge.algos.trail.config import (
    MARKET_AMENDS_PER_MIN,
    MARKET_GRACE_MS,
    MIN_GAP_MS,
    MISSING_GRACE_MS,
    TRAIL_COI_BASE,
    TRAIL_COI_END,
)
from mayedge.algos.trail.job import TrailRunner
from mayedge.algos.trail.plan import TrailParams, TrailRefused, check_start
from mayedge.config import settings
from mayedge.lighter.coi import is_algo_client_order

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from planner_harness import MI, FakeClock, FakeVenue  # noqa: E402


class FakeTrailBook:
    def __init__(self, venue: FakeVenue) -> None:
        self.venue = venue
        self.coi = TRAIL_COI_BASE
        self.finished: list[TrailRunner] = []
        self.amend_budget = 1_000

    def publish(self) -> None:
        pass

    def finish(self, job: TrailRunner) -> None:
        self.finished.append(job)

    def alloc_coi(self) -> int:
        self.coi += 1
        return self.coi

    def execution(self):
        return self.venue.execution()

    def take_amend(self, market_index: int, now_ms: int) -> bool:
        if self.amend_budget <= 0:
            return False
        self.amend_budget -= 1
        return True


def _params(**kw: Any) -> TrailParams:
    base: dict[str, Any] = {"kind": "stop", "distance": "1", "distance_kind": "price"}
    base.update(kw)
    return TrailParams.from_json(base)


class TrailJobTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._td = TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        db_path = patch.object(settings, "db_path", str(Path(self._td.name) / "mayedge.db"))
        db_path.start()
        self.addCleanup(db_path.stop)
        self.addCleanup(store.close_db)
        store.close_db()
        self.clock = FakeClock()
        p = patch("mayedge.algos.common.now_ms", self.clock)
        p.start()
        self.addCleanup(p.stop)
        self.venue = FakeVenue()
        self.book = FakeTrailBook(self.venue)

    def _long(self, size: str = "2") -> None:
        self.venue.position = D(size)
        self.venue.entry = D("100")

    async def _start(
        self, params: TrailParams, replaced: list[dict[str, Any]] | None = None
    ) -> TrailRunner:
        ctx, _ = planner_venue.market_context(self.venue.execution(), MI)
        resolved = check_start(params, ctx)
        params.side = resolved.side
        job = TrailRunner(self.book)
        await job.start(
            algo_id="TR-0001",
            market_index=MI,
            symbol="ETH",
            params=params,
            resolved=resolved,
            replaced=replaced,
        )
        await job._halt()
        job._stop.clear()
        return job

    async def _tick(self, job: TrailRunner, ms: int = 0) -> None:
        self.clock.advance(ms)
        await job._evaluate()

    async def _mark(self, job: TrailRunner, px: str, ms: int = MIN_GAP_MS) -> None:
        self.venue.set_mark(px)
        await self._tick(job, ms)

    async def _print(self, job: TrailRunner, *prices: str, ms: int = 0) -> None:
        # Mark keeps near Last; the venue checks a trigger against mark.
        self.venue.set_mark(prices[-1])
        job.on_gateway({"type": "prints", "market_index": MI, "prices": list(prices)})
        await self._tick(job, ms)

    def _stop_row(self) -> dict[str, Any]:
        rows = [o for o in self.venue.orders.values() if o["order_type"] == "stop-loss"]
        self.assertEqual(len(rows), 1)
        return rows[0]

    # ── Stop ──

    async def test_the_stop_goes_on_at_start(self) -> None:
        self._long()
        await self._start(_params())
        sent = self.venue.sent("trigger_sl")
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["trigger"], "99")
        self.assertEqual(sent[0]["size"], "0")
        self.assertEqual(sent[0]["side"], "sell")

    async def test_the_start_price_is_used_when_given(self) -> None:
        self._long()
        await self._start(_params(start="95", activation="105"))
        self.assertEqual(self.venue.sent("trigger_sl")[0]["trigger"], "95")

    async def test_the_stop_follows_mark_by_amend(self) -> None:
        self._long()
        job = await self._start(_params())
        await self._mark(job, "103")
        self.assertEqual(self.venue.sent("amend")[-1]["trigger"], "102")
        self.assertEqual(self._stop_row()["trigger_price"], "102")
        self.assertEqual(job.state.venue_trigger, D("102"))

    async def test_trigger_never_moves_back(self) -> None:
        self._long()
        job = await self._start(_params())
        await self._mark(job, "103")
        await self._mark(job, "102.5")
        self.assertEqual(len(self.venue.sent("amend")), 1)
        self.assertEqual(job.state.point.trigger, D("102"))

    async def test_a_move_smaller_than_the_step_is_not_sent(self) -> None:
        self._long()
        job = await self._start(_params())
        # The step is 10% of 1 = 0.1. 0.05 better is not enough.
        await self._mark(job, "100.05")
        self.assertEqual(self.venue.sent("amend"), [])
        await self._mark(job, "100.1")
        self.assertEqual(len(self.venue.sent("amend")), 1)

    async def test_moves_wait_the_min_gap(self) -> None:
        self._long()
        job = await self._start(_params())
        await self._mark(job, "102", ms=MIN_GAP_MS)
        await self._mark(job, "104", ms=1_000)
        self.assertEqual(len(self.venue.sent("amend")), 1)
        await self._tick(job, MIN_GAP_MS)
        self.assertEqual(self.venue.sent("amend")[-1]["trigger"], "103")

    async def test_a_market_shares_one_amend_budget(self) -> None:
        self._long()
        job = await self._start(_params())
        self.book.amend_budget = 0
        await self._mark(job, "103")
        self.assertEqual(self.venue.sent("amend"), [])
        real = TrailBook(execution=self.venue.execution, broadcast=lambda _p: None)
        now = 1_000_000
        took = [real.take_amend(MI, now) for _ in range(MARKET_AMENDS_PER_MIN + 1)]
        self.assertEqual(took.count(True), MARKET_AMENDS_PER_MIN)
        self.assertFalse(took[-1])
        self.assertTrue(real.take_amend(MI, now + 60_000))
        self.assertTrue(real.take_amend(MI + 1, now))

    async def test_the_stop_holds_until_activation(self) -> None:
        self._long()
        job = await self._start(_params(start="95", activation="105"))
        await self._mark(job, "104")
        self.assertEqual(self.venue.sent("amend"), [])
        await self._mark(job, "105")
        self.assertEqual(self.venue.sent("amend")[-1]["trigger"], "104")

    async def test_a_trail_stop_replaces_stop_tickets(self) -> None:
        self._long()
        ticket = {
            "market_index": MI,
            "order_index": "77",
            "client_order_index": "1000000005",
            "order_type": "stop-loss",
            "side": "sell",
        }
        self.venue.orders[1_000_000_005] = ticket
        tp = {
            "market_index": MI,
            "order_index": "78",
            "client_order_index": "1000000006",
            "order_type": "take-profit",
            "side": "sell",
        }
        self.venue.orders[1_000_000_006] = tp
        book = TrailBook(execution=self.venue.execution, broadcast=lambda _p: None)
        preview = book.preview_from_body(
            {"market_index": MI, "kind": "stop", "distance": "1", "distance_kind": "price"}
        )
        self.assertEqual([o["order_index"] for o in preview["replaces"]], ["77"])
        await self._start(_params(), replaced=preview["replaces"])
        kinds = [k for k, _ in self.venue.calls]
        self.assertLess(kinds.index("trigger_sl"), kinds.index("cancel"))
        self.assertNotIn(1_000_000_005, self.venue.orders)
        self.assertIn(1_000_000_006, self.venue.orders)

    async def test_flat_ends_the_trail(self) -> None:
        self._long()
        job = await self._start(_params())
        coi = int(self._stop_row()["client_order_index"])
        self.venue.trigger(coi)
        await self._tick(job)
        await self._tick(job, MISSING_GRACE_MS)
        self.assertEqual(job.state.status, ChaseStatus.DONE)
        self.assertEqual(job.state.reason, "flat")

    async def test_a_missing_stop_is_put_back(self) -> None:
        self._long()
        job = await self._start(_params())
        await self._mark(job, "103")
        coi = int(self._stop_row()["client_order_index"])
        await self._tick(job)
        del self.venue.orders[coi]
        await self._tick(job)
        await self._tick(job, MISSING_GRACE_MS)
        sent = self.venue.sent("trigger_sl")
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[-1]["trigger"], "102")

    async def test_a_stop_mark_has_passed_closes_at_market(self) -> None:
        self._long()
        job = await self._start(_params())
        coi = int(self._stop_row()["client_order_index"])
        await self._tick(job)
        del self.venue.orders[coi]
        # Mark is through 99 before the stop can go back.
        self.venue.set_mark("98")
        await self._tick(job)
        await self._tick(job, MISSING_GRACE_MS)
        market = self.venue.sent("market")
        self.assertEqual(len(market), 1)
        self.assertTrue(market[0]["reduce_only"])
        self.assertEqual(market[0]["size"], "2")

    async def test_stop_keep_leaves_a_stop_ticket(self) -> None:
        self._long()
        job = await self._start(_params())
        await self._mark(job, "103")
        await job.stop(keep_stop=True)
        kept = self.venue.sent("trigger_sl")[-1]
        self.assertEqual(kept["trigger"], "102")
        self.assertFalse(is_algo_client_order(kept["client_order_index"]))
        self.assertEqual(job.state.status, ChaseStatus.STOPPED)
        # Only the kept Ticket is left.
        self.assertEqual(
            [o["client_order_index"] for o in self.venue.orders.values()],
            [str(kept["client_order_index"])],
        )

    async def test_stopping_without_keep_cancels_the_stop(self) -> None:
        self._long()
        job = await self._start(_params())
        await job.stop()
        self.assertEqual(self.venue.orders, {})

    async def test_shutdown_leaves_the_stop_on(self) -> None:
        self._long()
        job = await self._start(_params())
        await job.drain_for_shutdown()
        self.assertEqual(len(self.venue.orders), 1)

    async def test_a_restart_carries_on_from_the_saved_best_price(self) -> None:
        self._long()
        job = await self._start(_params())
        await self._mark(job, "103")
        row = job.snapshot()
        row.update(job.state.ledger.to_persist())
        again = TrailRunner(self.book)
        again.hydrate_from_row(row)
        self.assertEqual(again.state.point.best, D("103"))
        self.assertEqual(again.state.point.trigger, D("102"))
        self.assertEqual(again.state.venue_trigger, D("102"))
        # Mark is lower after the restart: nothing moves back.
        self.venue.set_mark("101")
        await again._evaluate()
        self.assertEqual(len(self.venue.sent("amend")), 1)

    async def test_a_stale_feed_stops_following(self) -> None:
        self._long()
        job = await self._start(_params())
        health = {"market_ws": "down"}
        ex = self.venue.execution()
        ex.feed_health = lambda: health
        with patch.object(self.book, "execution", return_value=ex):
            await self._mark(job, "103")
            self.assertEqual(self.venue.sent("amend"), [])
            self.assertFalse(job.snapshot()["trail"]["following"])
            health["market_ws"] = "live"
            await self._tick(job)
        self.assertEqual(len(self.venue.sent("amend")), 1)

    async def test_an_edit_never_moves_the_trigger_back(self) -> None:
        self._long()
        job = await self._start(_params())
        await self._mark(job, "103")
        await job.edit(_params(distance="3"))
        await self._mark(job, "103")
        self.assertEqual(job.state.point.trigger, D("102"))
        await self._mark(job, "106")
        self.assertEqual(job.state.point.trigger, D("103"))

    # ── Take Profit ──

    async def test_take_profit_needs_an_activation_past_mark(self) -> None:
        self._long()
        ctx, _ = planner_venue.market_context(self.venue.execution(), MI)
        with self.assertRaises(TrailRefused):
            check_start(_params(kind="tp"), ctx)
        with self.assertRaises(TrailRefused):
            check_start(_params(kind="tp", activation="99"), ctx)

    async def test_take_profit_size_is_a_share_of_the_position(self) -> None:
        self._long("2")
        ctx, _ = planner_venue.market_context(self.venue.execution(), MI)
        r = check_start(_params(kind="tp", activation="105", size_pct="33"), ctx)
        self.assertEqual(r.qty, D("0.6"))

    async def test_take_profit_places_its_stop_at_activation(self) -> None:
        self._long()
        job = await self._start(_params(kind="tp", activation="105", size_pct="50"))
        await self._mark(job, "104")
        self.assertEqual(self.venue.sent("trigger_sl"), [])
        await self._mark(job, "105")
        sent = self.venue.sent("trigger_sl")
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["trigger"], "104")
        self.assertEqual(sent[0]["size"], "1")

    async def test_take_profit_ends_when_its_stop_fills(self) -> None:
        self._long()
        job = await self._start(_params(kind="tp", activation="105", size_pct="50"))
        await self._mark(job, "105")
        coi = int(self._stop_row()["client_order_index"])
        await self._tick(job)
        self.venue.fill(coi, "1", price="104")
        await self._tick(job)
        await self._tick(job, MISSING_GRACE_MS)
        self.assertEqual(job.state.status, ChaseStatus.DONE)
        self.assertEqual(job.state.reason, "filled")

    # ── Entry ──

    async def test_entry_fires_a_market_order_when_price_comes_back(self) -> None:
        job = await self._start(_params(kind="entry", side="buy", size="1", activation="95"))
        await self._mark(job, "96")
        await self._mark(job, "95")
        await self._mark(job, "93")
        self.assertEqual(self.venue.sent("market"), [])
        self.assertEqual(job.state.point.trigger, D("94"))
        await self._mark(job, "94")
        market = self.venue.sent("market")
        self.assertEqual(len(market), 1)
        self.assertEqual(market[0]["side"], "buy")
        self.assertFalse(market[0]["reduce_only"])
        self.assertEqual(market[0]["size"], "1")

    async def test_activation_waits_for_its_price(self) -> None:
        job = await self._start(_params(kind="entry", side="buy", size="1", activation="95"))
        # Back up 1 from 98 is not a fire: the Trail is not active yet.
        await self._mark(job, "98")
        await self._mark(job, "99.5")
        self.assertEqual(self.venue.sent("market"), [])
        self.assertFalse(job.state.point.active)

    async def test_entry_ends_once_its_order_is_done(self) -> None:
        job = await self._start(_params(kind="entry", side="buy", size="1"))
        await self._mark(job, "98")
        await self._mark(job, "99")
        self.assertEqual(len(self.venue.sent("market")), 1)
        self.venue.move("1", "99")
        await self._tick(job)
        self.assertEqual(job.state.status, ChaseStatus.DONE)
        self.assertEqual(job.state.reason, "filled 1")

    async def test_an_entry_with_no_fill_ends_after_the_grace(self) -> None:
        job = await self._start(_params(kind="entry", side="buy", size="1"))
        await self._mark(job, "98")
        await self._mark(job, "99")
        await self._tick(job, MARKET_GRACE_MS)
        self.assertEqual(job.state.reason, "entry did not fill")

    async def test_an_expired_entry_ends_unfilled(self) -> None:
        job = await self._start(_params(kind="entry", side="buy", size="1", expiry_min="1"))
        await self._tick(job, 60_000)
        self.assertEqual(job.state.status, ChaseStatus.DONE)
        self.assertEqual(job.state.reason, "entry expired")

    # ── Last ──

    async def test_last_follows_every_print(self) -> None:
        self._long()
        job = await self._start(_params(reference="last"))
        await self._print(job, "101", "104", "102")
        self.assertEqual(job.state.point.best, D("104"))
        self.assertEqual(job.state.point.trigger, D("103"))

    async def test_the_backstop_sits_one_step_behind(self) -> None:
        self._long()
        job = await self._start(_params(reference="last"))
        # The trigger is 99 and the step 0.1: the backstop goes on at 98.9.
        self.assertEqual(self.venue.sent("trigger_sl")[0]["trigger"], "98.9")
        await self._print(job, "104", ms=MIN_GAP_MS)
        self.assertEqual(self.venue.sent("amend")[-1]["trigger"], "102.9")

    async def test_an_exit_on_last_fires_on_a_print(self) -> None:
        self._long()
        job = await self._start(_params(reference="last"))
        await self._print(job, "104", "103")
        market = self.venue.sent("market")
        self.assertEqual(len(market), 1)
        self.assertTrue(market[0]["reduce_only"])
        self.assertEqual(market[0]["size"], "2")

    async def test_a_fire_is_not_held_by_the_gap(self) -> None:
        self._long()
        job = await self._start(_params(reference="last"))
        self.book.amend_budget = 0
        await self._print(job, "104")
        await self._print(job, "103", ms=1)
        self.assertEqual(len(self.venue.sent("market")), 1)

    async def test_the_backstop_comes_off_after_a_fire(self) -> None:
        self._long()
        job = await self._start(
            _params(kind="tp", reference="last", activation="105", size_pct="50")
        )
        await self._print(job, "105", ms=MIN_GAP_MS)
        self.assertEqual(self.venue.sent("trigger_sl")[0]["trigger"], "103.9")
        await self._print(job, "104")
        self.assertEqual(len(self.venue.sent("market")), 1)
        self.venue.move("-1", "104")
        await self._tick(job)
        self.assertEqual(job.state.status, ChaseStatus.DONE)
        self.assertEqual(self.venue.orders, {})

    # ── start ──

    async def test_bad_inputs_refuse(self) -> None:
        self._long()
        ctx, _ = planner_venue.market_context(self.venue.execution(), MI)
        for bad in (
            _params(distance="0.01"),
            _params(start="101"),
            _params(activation="99"),
            _params(kind="entry", side="buy", size="1", activation="101"),
        ):
            with self.assertRaises(TrailRefused):
                check_start(bad, ctx)

    async def test_one_trail_stop_per_market(self) -> None:
        self._long()
        book = TrailBook(execution=self.venue.execution, broadcast=lambda _p: None)
        with patch("mayedge.algos.trail.book.store"):
            body = {"market_index": MI, "kind": "stop", "distance": "1", "distance_kind": "price"}
            await book.start_from_body(body)
            with self.assertRaises(TrailRefused):
                await book.start_from_body(body)
            await book.stop()

    async def test_cancel_all_stops_the_trails(self) -> None:
        self._long()
        book = TrailBook(execution=self.venue.execution, broadcast=lambda _p: None)
        with patch("mayedge.algos.trail.book.store"):
            await book.start_from_body(
                {"market_index": MI, "kind": "stop", "distance": "1", "distance_kind": "price"}
            )
            self.assertTrue(book.live_on_market(MI))
            await book.pause_for_market(MI)
        self.assertFalse(book.live_on_market(MI))
        self.assertEqual(self.venue.orders, {})

    async def test_trail_cois_are_in_their_band(self) -> None:
        self.assertTrue(is_algo_client_order(TRAIL_COI_BASE + 1))
        self.assertFalse(is_algo_client_order(TRAIL_COI_END))
