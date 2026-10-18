"""Planner's trailing parts: E9, M10, M11 and P9 Trail. Rule ids are docs/planner-rules.md."""

from __future__ import annotations

import dataclasses
import sys
from decimal import Decimal as D
from pathlib import Path
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from mayedge.algos.chase import util
from mayedge.algos.chase.state import ChaseStatus
from mayedge.algos.planner import venue as planner_venue
from mayedge.algos.planner.config import MISSING_GRACE_MS
from mayedge.algos.planner.job import PlannerRunner
from mayedge.algos.planner.plan import (
    EntryTrail,
    PlannerParams,
    PlanRefused,
    Target,
    TrailStop,
    build_plan,
)
from mayedge.algos.trail.config import MIN_GAP_MS

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from planner_harness import MI, FakeBook, FakeClock, FakeVenue  # noqa: E402

LONG = PlannerParams(
    mode="enter",
    side="buy",
    stop=D("95"),
    targets=[
        Target("r", D("1"), D("50"), "trigger"),
        Target("r", D("2"), D("50"), "trigger"),
    ],
    entry_type="limit",
    entry_price=D("100"),
    size=D("2"),
)


def _p(**kw: Any) -> PlannerParams:
    return dataclasses.replace(LONG, **kw)


class PlannerTrailTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        p = patch.object(util, "now_ms", self.clock)
        p.start()
        self.addCleanup(p.stop)
        self.venue = FakeVenue()
        self.book = FakeBook(self.venue)

    async def _start(self, params: PlannerParams) -> PlannerRunner:
        job = PlannerRunner(self.book)
        ctx, _ = planner_venue.market_context(self.venue.execution(), MI)
        plan = build_plan(params, ctx)
        await job.start(algo_id="PL-0001", market_index=MI, symbol="ETH", params=params, plan=plan)
        await job._halt()
        job._stop.clear()
        return job

    def _coi(self, kind: str, n: int = 0) -> int:
        return int(self.venue.sent(kind)[n]["client_order_index"])

    async def _tick(self, job: PlannerRunner, ms: int = 0) -> None:
        self.clock.advance(ms)
        await job._evaluate()

    async def _mark(self, job: PlannerRunner, px: str, ms: int = MIN_GAP_MS) -> None:
        self.venue.set_mark(px)
        await self._tick(job, ms)

    async def _managed(self, params: PlannerParams) -> PlannerRunner:
        job = await self._start(params)
        self.venue.fill(self._coi("limit"), "2")
        await self._tick(job)
        self.assertEqual(job.state.phase, "managing")
        return job

    def _amends(self) -> list[str]:
        return [a["trigger"] for a in self.venue.sent("amend")]

    # ── E9: Trail entry ──

    async def test_a_trail_entry_fires_and_sizes_from_its_price(self) -> None:
        params = _p(
            entry_type="trail",
            entry_price=None,
            size=None,
            risk_pct=D("1"),
            entry_trail=EntryTrail(distance=D("1"), distance_kind="price", activation=D("98")),
        )
        job = await self._start(params)
        self.assertEqual(self.venue.calls, [])
        await self._mark(job, "99")
        self.assertFalse(job.state.trails["entry"].active)
        await self._mark(job, "98")
        await self._mark(job, "97")
        self.assertEqual(job.state.trails["entry"].trigger, D("98"))
        self.assertEqual(self.venue.sent("market"), [])
        await self._mark(job, "98")
        market = self.venue.sent("market")
        self.assertEqual(len(market), 1)
        self.assertEqual(market[0]["side"], "buy")
        # 1% of 10,000 over (98 − 95) = 33.33, down to the lot.
        self.assertEqual(market[0]["size"], "33.3")
        assert job.state.plan is not None
        self.assertEqual(job.state.plan.entry, D("98"))
        self.assertEqual([t.price for t in job.state.plan.targets], [D("101"), D("104")])

    async def test_a_trail_entry_through_the_stop_ends(self) -> None:
        params = _p(
            entry_type="trail",
            entry_price=None,
            entry_trail=EntryTrail(distance=D("1"), distance_kind="price"),
        )
        job = await self._start(params)
        await self._mark(job, "94")
        self.assertEqual(job.state.status, ChaseStatus.DONE)
        self.assertEqual(job.state.reason, "stop reached before the entry fired")
        self.assertEqual(self.venue.sent("market"), [])

    async def test_a_trail_entry_activation_past_the_stop_refuses(self) -> None:
        ctx, _ = planner_venue.market_context(self.venue.execution(), MI)
        params = _p(
            entry_type="trail",
            entry_price=None,
            entry_trail=EntryTrail(distance=D("1"), distance_kind="price", activation=D("94")),
        )
        with self.assertRaises(PlanRefused):
            build_plan(params, ctx)

    # ── M10: Trail stop ──

    async def test_the_trail_stop_starts_after_its_target(self) -> None:
        params = _p(trail_stop=TrailStop(start="target", after=1, distance=D("1"), unit="r"))
        job = await self._managed(params)
        await self._mark(job, "104")
        self.assertEqual(self._amends(), [])
        self.venue.set_mark("105")
        self.venue.fill(self._coi("trigger_tp", 0), "1")
        await self._tick(job)
        # Breakeven first; the trail at 105 − 5 = 100 does not beat it.
        self.assertEqual(self._amends(), ["100"])
        await self._mark(job, "108")
        self.assertEqual(self._amends(), ["100", "103"])
        self.assertEqual(job.state.stop_trigger, D("103"))

    async def test_the_trail_stop_never_goes_below_the_stepped_stop(self) -> None:
        params = _p(trail_stop=TrailStop(start="target", after=1, distance=D("10"), unit="r"))
        job = await self._managed(params)
        self.venue.set_mark("105")
        self.venue.fill(self._coi("trigger_tp", 0), "1")
        await self._tick(job)
        await self._mark(job, "108")
        self.assertEqual(self._amends(), ["100"])
        self.assertEqual(job.state.trails["stop"].trigger, D("100"))

    async def test_the_trail_stop_starts_at_an_r_multiple(self) -> None:
        params = _p(trail_stop=TrailStop(start="r", at_r=D("1.5"), distance=D("1"), unit="r"))
        job = await self._managed(params)
        await self._mark(job, "104")
        self.assertEqual(self._amends(), [])
        await self._mark(job, "108")
        self.assertEqual(self._amends(), ["103"])

    async def test_a_paused_planner_does_not_trail(self) -> None:
        params = _p(trail_stop=TrailStop(start="r", at_r=D("1"), distance=D("1"), unit="r"))
        job = await self._managed(params)
        await job.pause()
        await self._mark(job, "108")
        self.assertEqual(self._amends(), [])

    async def test_an_all_runner_plan_trails_on_last(self) -> None:
        params = _p(
            targets=[],
            reference="last",
            trail_stop=TrailStop(start="last", distance=D("1"), unit="pct"),
        )
        job = await self._managed(params)
        self.venue.set_mark("104")
        job.on_gateway({"type": "prints", "market_index": MI, "prices": ["102", "104"]})
        await self._tick(job, MIN_GAP_MS)
        # 104 − 1% = 102.96; the backstop one step (0.104) behind, to the tick: 102.85.
        self.assertEqual(job.state.trails["stop"].trigger, D("102.96"))
        self.assertEqual(self._amends(), ["102.85"])
        job.on_gateway({"type": "prints", "market_index": MI, "prices": ["102.9"]})
        await self._tick(job)
        market = self.venue.sent("market")
        self.assertEqual(len(market), 1)
        self.assertTrue(market[0]["reduce_only"])
        self.assertEqual(market[0]["size"], "2")

    async def test_no_targets_needs_a_trail_stop(self) -> None:
        ctx, _ = planner_venue.market_context(self.venue.execution(), MI)
        with self.assertRaises(PlanRefused):
            build_plan(_p(targets=[]), ctx)

    # ── P9: Trail targets ──

    async def test_a_trail_target_follows_from_its_price(self) -> None:
        trail = Target("r", D("2"), D("50"), "trail", trail_distance=D("0.4"), trail_unit="r")
        params = _p(targets=[Target("r", D("1"), D("50"), "trigger"), trail])
        job = await self._managed(params)
        # Only TP1 is on the venue; TP2 waits for 110.
        self.assertEqual(len(self.venue.sent("trigger_tp")), 1)
        await self._mark(job, "109")
        self.assertEqual(self.venue.sent("trigger_sl")[1:], [])
        await self._mark(job, "110")
        placed = self.venue.sent("trigger_sl")[-1]
        self.assertEqual(placed["trigger"], "108")
        self.assertEqual(placed["size"], "1")
        await self._mark(job, "113")
        self.assertEqual(self._amends()[-1], "111")
        coi = int(placed["client_order_index"])
        await self._tick(job)
        self.venue.fill(coi, "1", price="111")
        await self._tick(job)
        await self._tick(job, MISSING_GRACE_MS)
        tp2 = job._latest("tp2")
        assert tp2 is not None
        self.assertEqual(tp2.status, "filled")

    async def test_step_up_after_a_trail_target_goes_to_its_fill_price(self) -> None:
        trail = Target("r", D("2"), D("30"), "trail", trail_distance=D("1"), trail_unit="pct")
        params = _p(
            stop_steps="ladder",
            targets=[
                Target("r", D("1"), D("30"), "trigger"),
                trail,
                Target("r", D("3"), D("30"), "trigger"),
            ],
        )
        job = await self._managed(params)
        self.venue.set_mark("105")
        self.venue.fill(self._coi("trigger_tp", 0), "0.6")
        await self._tick(job)
        await self._mark(job, "110")
        await self._mark(job, "112.5")
        stop2 = int(self.venue.sent("trigger_sl")[-1]["client_order_index"])
        trigger = self.venue.orders[stop2]["trigger_price"]
        self.venue.fill(stop2, "0.6", price=trigger)
        await self._tick(job)
        await self._tick(job, MISSING_GRACE_MS)
        self.venue.set_mark("116")
        self.venue.fill(self._coi("trigger_tp", 1), "0.6")
        await self._tick(job)
        self.assertEqual(job.state.stop_trigger, D(trigger))
        self.assertNotEqual(D(trigger), D("110"))
