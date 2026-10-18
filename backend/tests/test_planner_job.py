from __future__ import annotations

import dataclasses
import sys
from decimal import Decimal as D
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from mayedge.algos.chase import util
from mayedge.algos.chase.config import MIN_REQUOTE_MS
from mayedge.algos.chase.state import ChaseStatus
from mayedge.algos.planner import venue as planner_venue
from mayedge.algos.planner.config import MISMATCH_GRACE_MS, MISSING_GRACE_MS, PLANNER_COI_BASE
from mayedge.algos.planner.job import PlannerRunner
from mayedge.algos.planner.plan import EntryChase, PlannerParams, Target, build_plan

# Allow `from planner_harness import ...` when discover runs from backend/
_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from planner_harness import MI, FakeBook, FakeClock, FakeVenue  # noqa: E402

LONG = PlannerParams(
    mode="enter",
    side="buy",
    stop=D("95"),
    # Triggers here; Limit targets have their own tests below.
    targets=[
        Target("r", D("1"), D("50"), "trigger"),
        Target("r", D("2"), D("50"), "trigger"),
    ],
    entry_type="limit",
    entry_price=D("100"),
    size=D("2"),
)

# E10: works 2 between 99 and 100.5, one Clip of 1 at a time, 4 bps behind the touch.
CHASE = dataclasses.replace(
    LONG,
    entry_type="chase",
    entry_price=None,
    entry_chase=EntryChase(low=D("99"), high=D("100.5"), offset_bps=D("4"), clip=D("1")),
)


class PlannerJobTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        p = patch.object(util, "now_ms", self.clock)
        p.start()
        self.addCleanup(p.stop)
        self.venue = FakeVenue()
        self.book = FakeBook(self.venue)

    async def _start(self, params: PlannerParams = LONG, **kw) -> PlannerRunner:
        job = PlannerRunner(self.book)
        ctx, _ = planner_venue.market_context(self.venue.execution(), MI)
        plan = build_plan(params, ctx)
        await job.start(
            algo_id="PL-0001", market_index=MI, symbol="ETH", params=params, plan=plan, **kw
        )
        # Tests drive the job by hand, not through its loop.
        await job._halt()
        job._stop.clear()
        return job

    def _coi(self, kind: str, n: int = 0) -> int:
        return int(self.venue.sent(kind)[n]["client_order_index"])

    async def _tick(self, job: PlannerRunner, ms: int = 0) -> None:
        self.clock.advance(ms)
        await job._evaluate()

    async def _managed(self) -> PlannerRunner:
        job = await self._start()
        self.venue.fill(self._coi("limit"), "2")
        await self._tick(job)
        self.assertEqual(job.state.phase, "managing")
        return job

    def _tp1_fills(self) -> None:
        self.venue.set_mark("105")
        self.venue.fill(self._coi("trigger_tp", 0), "1")

    # ── entry ──

    async def test_the_stop_goes_on_with_the_first_fill(self) -> None:
        job = await self._start()
        await self._tick(job)
        self.assertEqual(self.venue.sent("trigger_sl"), [])
        self.venue.fill(self._coi("limit"), "0.5")
        await self._tick(job)
        stop = self.venue.sent("trigger_sl")
        self.assertEqual(len(stop), 1)
        self.assertEqual(stop[0]["size"], "0")
        self.assertEqual(stop[0]["trigger"], "95")
        self.assertEqual(stop[0]["side"], "sell")
        self.venue.fill(self._coi("limit"), "0.5")
        await self._tick(job)
        self.assertEqual(len(self.venue.sent("trigger_sl")), 1)

    async def test_targets_go_on_once_the_entry_is_complete_from_its_actual_price(self) -> None:
        job = await self._start()
        self.venue.fill(self._coi("limit"), "1", price="100")
        await self._tick(job)
        self.assertEqual(self.venue.sent("trigger_tp"), [])
        self.venue.fill(self._coi("limit"), "1", price="99")
        await self._tick(job)
        tps = self.venue.sent("trigger_tp")
        # Entry 99.5, R 4.5: 1R at 104, 2R at 108.5 (rounded toward entry).
        self.assertEqual([t["trigger"] for t in tps], ["104", "108.5"])
        self.assertEqual([t["size"] for t in tps], ["1", "1"])
        self.assertTrue(all(t["kind"] == "limit" for t in tps))
        # P3: the risk is restated at the entry that filled.
        plan = job.state.plan
        assert plan is not None
        self.assertEqual(plan.entry, D("99.5"))
        self.assertEqual(plan.risk_usd, D("9"))

    async def test_the_entry_is_a_clip_on_planners_band(self) -> None:
        await self._start()
        limit = self.venue.sent("limit")[0]
        self.assertGreater(limit["client_order_index"], PLANNER_COI_BASE)
        self.assertEqual(limit["time_in_force"], "gtt")
        self.assertFalse(limit["reduce_only"])
        self.venue.calls.clear()
        self.venue.orders.clear()
        self.book.finished.clear()
        await self._start(dataclasses.replace(LONG, entry_type="market", slippage=0.02))
        market = self.venue.sent("market")[0]
        self.assertEqual(market["slippage"], 0.02)
        self.assertEqual(market["size"], "2")

    async def test_mark_through_the_stop_cancels_the_entry(self) -> None:
        job = await self._start()
        self.venue.set_mark("94.9")
        await self._tick(job)
        self.assertEqual(len(self.venue.sent("cancel")), 1)
        self.assertIn("stop reached", job.state.reason or "")

    async def test_an_expired_entry_protects_what_filled(self) -> None:
        job = await self._start(dataclasses.replace(LONG, expiry_min=1))
        self.venue.fill(self._coi("limit"), "1")
        await self._tick(job, 61_000)
        self.assertEqual(len(self.venue.sent("cancel")), 1)
        await self._tick(job)
        self.assertEqual(job.state.phase, "managing")
        self.assertEqual(len(self.venue.sent("trigger_sl")), 1)
        self.assertEqual([t["size"] for t in self.venue.sent("trigger_tp")], ["0.5", "0.5"])

    async def test_an_entry_that_never_fills_ends_the_planner(self) -> None:
        job = await self._start(dataclasses.replace(LONG, expiry_min=1))
        await self._tick(job, 61_000)
        await self._tick(job, MISSING_GRACE_MS)
        self.assertEqual(job.state.status, ChaseStatus.DONE)
        self.assertEqual(self.book.finished, [job])
        self.assertEqual(self.venue.sent("trigger_sl"), [])

    async def test_a_vanished_entry_is_not_a_fill(self) -> None:
        job = await self._start()
        await self._tick(job)
        self.venue.orders.clear()
        await self._tick(job)
        await self._tick(job, MISSING_GRACE_MS)
        await self._tick(job, MISSING_GRACE_MS)
        self.assertEqual(job.state.status, ChaseStatus.DONE)
        self.assertEqual(job.state.entry_filled, D("0"))
        self.assertEqual(self.venue.sent("trigger_sl"), [])

    async def test_a_stop_mark_has_passed_closes_at_market(self) -> None:
        job = await self._start()
        self.venue.fill(self._coi("limit"), "1")
        self.venue.set_mark("94")
        await self._tick(job)
        close = self.venue.sent("market")
        self.assertEqual(len(close), 1)
        self.assertTrue(close[0]["reduce_only"])
        self.assertEqual(close[0]["size"], "1")
        self.assertEqual(close[0]["side"], "sell")

    async def test_a_limit_target_rests_on_the_book(self) -> None:
        params = dataclasses.replace(
            LONG,
            targets=[Target("r", D("1"), D("50")), Target("r", D("2"), D("50"), "trigger")],
        )
        job = await self._start(params)
        self.venue.fill(self._coi("limit"), "2")
        await self._tick(job)
        rested = self.venue.sent("limit")[1:]
        self.assertEqual(len(rested), 1)
        self.assertEqual(rested[0]["price"], "105")
        self.assertEqual(rested[0]["size"], "1")
        self.assertEqual(rested[0]["side"], "sell")
        self.assertTrue(rested[0]["reduce_only"])
        self.assertEqual(rested[0]["time_in_force"], "gtt")
        self.assertEqual([t["trigger"] for t in self.venue.sent("trigger_tp")], ["110"])

    async def test_a_limit_target_fill_takes_the_stop_step(self) -> None:
        params = dataclasses.replace(
            LONG, targets=[Target("r", D("1"), D("50")), Target("r", D("2"), D("50"))]
        )
        job = await self._start(params)
        self.venue.fill(self._coi("limit"), "2")
        await self._tick(job)
        tp1 = self._coi("limit", 1)
        await self._tick(job)
        self.venue.set_mark("105.5")
        self.venue.fill(tp1, "1")
        await self._tick(job)
        self.assertEqual([a["trigger"] for a in self.venue.sent("amend")], ["100"])
        self.assertEqual(job.state.steps_done, 1)

    # ── manage ──

    async def test_breakeven_once_the_first_target_fills(self) -> None:
        job = await self._managed()
        self._tp1_fills()
        await self._tick(job)
        amends = self.venue.sent("amend")
        self.assertEqual(len(amends), 1)
        self.assertEqual(amends[0]["trigger"], "100")
        self.assertEqual(job.state.steps_done, 1)
        await self._tick(job)
        self.assertEqual(len(self.venue.sent("amend")), 1)
        self.assertEqual(job.state.expected_size, D("1"))

    async def test_breakeven_covers_the_round_trip_fee(self) -> None:
        payload = self.venue.payload
        self.venue.payload = lambda: {**payload(), "taker_fee_bps": "5"}  # type: ignore[method-assign]
        job = await self._managed()
        self._tp1_fills()
        await self._tick(job)
        self.assertEqual(self.venue.sent("amend")[0]["trigger"], "100.1")

    async def test_breakeven_waits_while_mark_sits_on_it(self) -> None:
        job = await self._managed()
        self.venue.fill(self._coi("trigger_tp", 0), "1")
        await self._tick(job)
        self.assertEqual(self.venue.sent("amend"), [])
        self.assertEqual(job.state.steps_done, 0)
        self.venue.set_mark("101")
        await self._tick(job)
        self.assertEqual(len(self.venue.sent("amend")), 1)

    async def _managed_ladder(self) -> PlannerRunner:
        params = dataclasses.replace(
            LONG,
            stop_steps="ladder",
            targets=[
                Target("r", D("1"), D("40"), "trigger"),
                Target("r", D("2"), D("40"), "trigger"),
                Target("r", D("3"), D("20"), "trigger"),
            ],
            size=D("5"),
        )
        job = await self._start(params)
        self.venue.fill(self._coi("limit"), "5")
        await self._tick(job)
        self.assertEqual(job.state.phase, "managing")
        return job

    async def test_step_up_moves_the_stop_to_the_target_before(self) -> None:
        job = await self._managed_ladder()
        self.venue.set_mark("106")
        self.venue.fill(self._coi("trigger_tp", 0), "2")
        await self._tick(job)
        self.assertEqual([a["trigger"] for a in self.venue.sent("amend")], ["100"])
        self.venue.set_mark("111")
        self.venue.fill(self._coi("trigger_tp", 1), "2")
        await self._tick(job)
        # TP1 was 105: after TP2 the stop sits there.
        self.assertEqual([a["trigger"] for a in self.venue.sent("amend")], ["100", "105"])
        self.assertEqual(job.state.steps_done, 2)
        self.assertEqual(job.state.stop_trigger, D("105"))

    async def test_two_targets_at_once_take_the_furthest_step(self) -> None:
        job = await self._managed_ladder()
        self.venue.set_mark("111")
        self.venue.fill(self._coi("trigger_tp", 0), "2")
        self.venue.fill(self._coi("trigger_tp", 1), "2")
        await self._tick(job)
        self.assertEqual([a["trigger"] for a in self.venue.sent("amend")], ["105"])
        self.assertEqual(job.state.steps_done, 2)

    async def test_a_step_mark_has_passed_closes_at_market(self) -> None:
        job = await self._managed_ladder()
        self.venue.set_mark("106")
        self.venue.fill(self._coi("trigger_tp", 0), "2")
        await self._tick(job)
        # TP2 fills, then price falls back under TP1 before the step lands.
        self.venue.fill(self._coi("trigger_tp", 1), "2")
        self.venue.set_mark("104")
        await self._tick(job)
        close = self.venue.sent("market")
        self.assertEqual(len(close), 1)
        self.assertTrue(close[0]["reduce_only"])
        self.assertEqual(close[0]["size"], "1")
        self.assertIn("closed at market", job.state.reason or "")

    async def test_breakeven_takes_no_later_step(self) -> None:
        job = await self._managed_ladder()
        assert job.state.params is not None
        assert job.state.plan is not None
        self.assertEqual([s.to for s in job.state.plan.steps], ["breakeven", "tp1"])
        job.state.params = dataclasses.replace(job.state.params, stop_steps="breakeven")
        job.state.plan = dataclasses.replace(job.state.plan, steps=job.state.plan.steps[:1])
        self.venue.set_mark("111")
        self.venue.fill(self._coi("trigger_tp", 0), "2")
        self.venue.fill(self._coi("trigger_tp", 1), "2")
        await self._tick(job)
        self.assertEqual([a["trigger"] for a in self.venue.sent("amend")], ["100"])

    async def test_a_planner_saved_before_steps_steps_to_breakeven(self) -> None:
        job = await self._managed()
        await job.drain_for_shutdown()
        row = {**job.snapshot(), **job.state.ledger.to_persist()}
        params = dict(row["params_json"])
        params.pop("stop_steps")
        params["breakeven"] = True
        params["runtime"]["planner"]["plan"].pop("steps")
        params["runtime"]["planner"].pop("steps_done")
        row["params_json"] = params
        again = PlannerRunner(self.book)
        again.hydrate_from_row(row)
        assert again.state.plan is not None
        self.assertEqual([s.to for s in again.state.plan.steps], ["breakeven"])

    async def test_breakeven_never_loosens_the_stop(self) -> None:
        job = await self._managed()
        job.state.stop_trigger = D("100.5")
        self._tp1_fills()
        await self._tick(job)
        self.assertEqual(self.venue.sent("amend"), [])
        self.assertEqual(job.state.steps_done, 1)

    async def test_an_outside_change_pauses_the_planner(self) -> None:
        job = await self._managed()
        self.venue.move("1", "100")
        await self._tick(job)
        self.assertEqual(job.state.status, ChaseStatus.RUNNING)
        await self._tick(job, MISMATCH_GRACE_MS)
        self.assertEqual(job.state.status, ChaseStatus.PAUSED)
        self.assertEqual(job.state.reason, "position changed")
        self.assertEqual(self.venue.sent("cancel"), [])
        self.assertEqual(len(self.venue.orders), 3)
        await job.unpause()
        await job._halt()
        job._stop.clear()
        self.assertEqual(job.state.status, ChaseStatus.RUNNING)
        self.assertEqual(job.state.expected_size, D("3"))

    async def test_a_restart_applies_the_target_fill_it_missed(self) -> None:
        job = await self._managed()
        await job.drain_for_shutdown()
        row = {**job.snapshot(), **job.state.ledger.to_persist()}
        self._tp1_fills()
        again = PlannerRunner(self.book)
        again.hydrate_from_row(row)
        await again.resume()
        await again._halt()
        again._stop.clear()
        self.assertEqual(len(self.venue.sent("amend")), 1)
        await self._tick(again)
        self.assertEqual(len(self.venue.sent("amend")), 1)

    async def test_shutdown_leaves_the_stop_and_targets_on(self) -> None:
        job = await self._managed()
        await job.drain_for_shutdown()
        self.assertEqual(self.venue.sent("cancel"), [])
        self.assertEqual(job.state.status, ChaseStatus.RUNNING)

    async def test_a_missing_stop_is_put_back(self) -> None:
        job = await self._managed()
        await self._tick(job)
        del self.venue.orders[self._coi("trigger_sl")]
        await self._tick(job)
        await self._tick(job, MISSING_GRACE_MS)
        self.assertEqual(len(self.venue.sent("trigger_sl")), 2)

    # ── end ──

    async def test_flat_ends_the_planner(self) -> None:
        job = await self._managed()
        self.venue.trigger(self._coi("trigger_sl"))
        await self._tick(job)
        self.assertEqual(job.state.status, ChaseStatus.RUNNING)
        await self._tick(job, MISSING_GRACE_MS)
        self.assertEqual(job.state.status, ChaseStatus.DONE)
        self.assertEqual(len(self.venue.sent("cancel")), 2)
        self.assertEqual(self.venue.orders, {})

    async def test_stopping_cancels_every_clip(self) -> None:
        job = await self._managed()
        await job.stop()
        self.assertEqual(job.state.status, ChaseStatus.STOPPED)
        self.assertEqual(self.venue.orders, {})
        self.assertEqual(self.book.finished, [job])

    # ── attach ──

    async def test_attach_puts_its_stop_on_before_pulling_tickets(self) -> None:
        self.venue.move("2", "100")
        self.venue.orders[1_000_000_009] = {
            "order_index": "77",
            "client_order_index": "1000000009",
            "market_index": MI,
            "side": "sell",
            "price": "89",
            "size": "0",
            "remaining": "0",
            "filled": "0",
            "order_type": "stop-loss",
            "reduce_only": True,
            "trigger_price": "90",
        }
        replaced = planner_venue.ticket_protects(self.venue.execution(), MI)
        self.assertEqual(len(replaced), 1)
        job = await self._start(
            dataclasses.replace(LONG, mode="attach", size=None, entry_price=None),
            replaced=replaced,
        )
        kinds = [k for k, _ in self.venue.calls]
        self.assertEqual(kinds[:2], ["trigger_sl", "cancel"])
        self.assertEqual(self.venue.sent("cancel")[0]["order_index"], 77)
        self.assertEqual(job.state.phase, "managing")
        self.assertEqual(len(self.venue.sent("trigger_tp")), 2)

    async def test_a_replan_moves_the_stop_and_redraws_the_targets(self) -> None:
        job = await self._managed()
        await job.replan(
            dataclasses.replace(
                LONG, stop=D("97"), targets=[Target("price", D("106"), D("100"), "trigger")]
            )
        )
        await job._halt()
        job._stop.clear()
        self.assertEqual(self.venue.sent("amend")[0]["trigger"], "97")
        self.assertEqual(len(self.venue.sent("cancel")), 2)
        tps = self.venue.sent("trigger_tp")
        self.assertEqual(tps[-1]["trigger"], "106")
        self.assertEqual(tps[-1]["size"], "2")

    # ── Chase entry ──

    async def _chasing(self) -> PlannerRunner:
        job = await self._start(CHASE)
        await self._tick(job)
        return job

    async def test_a_chase_entry_rests_behind_the_touch(self) -> None:
        job = await self._chasing()
        plan = job.state.plan
        assert plan is not None
        self.assertEqual(plan.entry, D("100.5"))  # E12: the band's worst fill
        clip = self.venue.sent("limit")[0]
        self.assertEqual(clip["time_in_force"], "post_only")
        self.assertEqual(clip["price"], "99.86")  # 99.9 less 4 bps, rounded down
        self.assertEqual(clip["size"], "1")
        self.assertGreater(clip["client_order_index"], PLANNER_COI_BASE)
        # It fills in pieces: the stop goes on with the first (E2), the next Clip follows.
        self.venue.fill(self._coi("limit"), "1")
        await self._tick(job)
        await self._tick(job, MISSING_GRACE_MS)
        self.assertEqual(len(self.venue.sent("trigger_sl")), 1)
        self.assertEqual(len(self.venue.sent("limit")), 2)
        self.venue.fill(self._coi("limit", 1), "1", price="99.5")
        await self._tick(job)
        self.assertEqual(job.state.phase, "managing")
        plan = job.state.plan
        assert plan is not None
        self.assertEqual(plan.entry, D("99.68"))  # E3: redrawn from the actual average
        self.assertEqual(len(self.venue.sent("trigger_tp")), 2)

    async def test_a_chase_entry_amends_as_the_book_walks(self) -> None:
        job = await self._chasing()
        self.venue.bid, self.venue.ask = "100.2", "100.3"
        await self._tick(job, 100)
        self.assertEqual(self.venue.sent("modify"), [])  # not inside 2s of the last move
        await self._tick(job, MIN_REQUOTE_MS)
        moved = self.venue.sent("modify")
        self.assertEqual(len(moved), 1)
        self.assertEqual(moved[0]["price"], "100.15")
        self.assertEqual(moved[0]["size"], "1")
        self.assertEqual(len(self.venue.sent("limit")), 1)

    async def test_a_chase_entry_waits_outside_its_band(self) -> None:
        job = await self._chasing()
        self.venue.bid, self.venue.ask = "98.8", "98.9"
        await self._tick(job)
        self.assertEqual(len(self.venue.sent("cancel")), 1)
        self.assertIn("below floor", job.state.reason or "")
        self.assertEqual(job.state.status, ChaseStatus.RUNNING)
        self.venue.bid, self.venue.ask = "99.9", "100.1"
        await self._tick(job)
        self.assertEqual(len(self.venue.sent("limit")), 2)

    async def test_a_chase_entry_waits_for_evidence_before_the_next_clip(self) -> None:
        job = await self._chasing()
        await self._tick(job)  # the feed shows it
        del self.venue.orders[self._coi("limit")]  # gone, with no trade and no Position
        await self._tick(job)
        await self._tick(job, MISSING_GRACE_MS)
        self.assertEqual(len(self.venue.sent("limit")), 1)
        self.assertIn("waits for the last Clip", job.state.reason or "")
        await self._tick(job, MISSING_GRACE_MS)
        self.assertEqual(len(self.venue.sent("limit")), 2)
        self.assertEqual(job.state.entry_filled, D("0"))  # E7: a vanished Clip is not a fill

    async def test_protect_now_ends_the_entry(self) -> None:
        job = await self._chasing()
        self.venue.fill(self._coi("limit"), "0.6")
        await self._tick(job)
        await job.finish_entry()
        await job._halt()
        self.assertEqual(len(self.venue.sent("cancel")), 1)
        self.assertEqual(job.state.phase, "managing")
        self.assertEqual([t["size"] for t in self.venue.sent("trigger_tp")], ["0.3", "0.3"])

    async def test_protect_now_with_nothing_filled_ends_the_planner(self) -> None:
        job = await self._chasing()
        await job.finish_entry()
        await job._halt()
        job._stop.clear()
        await self._tick(job, MISSING_GRACE_MS)
        self.assertEqual(job.state.status, ChaseStatus.DONE)
        self.assertEqual(self.venue.orders, {})

    async def test_shutdown_pulls_a_chase_entry(self) -> None:
        job = await self._chasing()
        await job.drain_for_shutdown()
        self.assertEqual(len(self.venue.sent("cancel")), 1)
        self.assertEqual(self.venue.orders, {})
        self.assertEqual(job.state.status, ChaseStatus.RUNNING)
