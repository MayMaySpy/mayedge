"""Massager job on the harness fakes: docs/massager-rules.md MS8–MS17."""

from __future__ import annotations

import asyncio
import contextlib
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest import IsolatedAsyncioTestCase

from mayedge.algos.chase.state import ChaseStatus
from mayedge.algos.massager.book import MassagerBook
from mayedge.algos.massager.config import OUTSIDE_GRACE_MS, is_massager_client_order
from mayedge.algos.massager.job import MassagerRunner
from mayedge.algos.massager.plan import MassagerParams, MassagerRefused

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from chase_harness import (  # noqa: E402
    FakeGateway,
    FakeOrderService,
    isolated_db,
    make_execution,
    patch_grid,
)
from venue_harness import FakeClock  # noqa: E402

D = Decimal
# ETH on the fakes: tick 0.01, size step 0.1. Band 90–110, 3 levels each side, Step 3.333….
PARAMS = MassagerParams(band_low=D("90"), band_high=D("110"), swing=D("3"), step=D("10") / 3)


class Rig:
    def __init__(self, *, bid: str = "100", ask: str = "100.10", position: str = "10") -> None:
        self.clock = FakeClock()
        self.gateway = FakeGateway()
        self.gateway.set_book(bid, ask)
        self.orders = FakeOrderService()
        if position != "0":
            self.orders.positions = [{"market_index": 1, "size": position, "entry_price": "98"}]
        self.book = MassagerBook(
            execution=lambda: make_execution(self.gateway, self.orders),
            broadcast=lambda _p: None,
        )
        self.job = MassagerRunner(self.book)

    def patch(self) -> Any:
        return patch_grid(self.clock, self.gateway, self.orders)

    async def start(self, params: MassagerParams = PARAMS) -> None:
        await self.job.start(algo_id="MS-0001", market_index=1, params=params)
        # Drive the job by hand: drop the background loop without setting its stop flag.
        task, self.job._task = self.job._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def tick(self, n: int = 6) -> None:
        """Several looks, far enough apart that the place gap and requote wait are open."""
        for _ in range(n):
            self.clock.advance(2_500)
            await self.job._evaluate()

    def resting(self) -> list[tuple[str, Decimal, Decimal]]:
        rows = [
            o
            for o in self.orders.open_orders
            if is_massager_client_order(o["client_order_index"]) and D(o["remaining"]) > 0
        ]
        return sorted((o["side"], D(o["price"]), D(o["remaining"])) for o in rows)

    def fill(self, side: str, price: str, remaining: str = "0") -> None:
        for o in self.orders.open_orders:
            if o["side"] == side and D(o["price"]) == D(price):
                self.orders.set_remaining(o["client_order_index"], remaining)
                return
        raise AssertionError(f"no {side} resting at {price}: {self.resting()}")

    def set_position(self, size: str) -> None:
        self.orders.positions = (
            [] if size == "0" else [{"market_index": 1, "size": size, "entry_price": "98"}]
        )


class MassagerJobCase(IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._db = isolated_db()
        cls._db.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._db.__exit__(None, None, None)


class StartTests(MassagerJobCase):
    async def test_start_takes_the_core_and_rests_two_levels_each_side(self) -> None:
        """MS1, MS9, MS17: at the Center there is no catch-up; four post-only Clips rest."""
        rig = Rig()
        with rig.patch():
            await rig.start()
            await rig.tick()
        self.assertEqual(
            rig.resting(),
            [
                ("buy", D("93.33"), D("1")),
                ("buy", D("96.67"), D("1")),
                ("sell", D("103.33"), D("1")),
                ("sell", D("106.67"), D("1")),
            ],
        )
        self.assertTrue(all(c["time_in_force"] == "post_only" for c in rig.orders.creates))
        self.assertTrue(all(not c["reduce_only"] for c in rig.orders.creates))
        snap = rig.job.snapshot()
        self.assertEqual((snap["core"], snap["lean"], snap["level"]), ("10", "0", 0))
        self.assertEqual(snap["status"], "running")
        self.assertEqual(snap["display_qty"], "1")

    async def test_no_position_is_refused(self) -> None:
        rig = Rig(position="0")
        with rig.patch(), self.assertRaises(MassagerRefused) as ctx:
            await rig.start()
        self.assertEqual(ctx.exception.rule, "MS1")
        self.assertEqual(rig.orders.creates, [])


class CatchUpTests(MassagerJobCase):
    async def test_the_catch_up_rests_at_the_touch_then_the_lattice_starts(self) -> None:
        """MS8, MS13: mid 104.05 has passed level +1, so it sells one Clip at the ask first."""
        rig = Rig(bid="104", ask="104.10")
        with rig.patch():
            await rig.start()
            await rig.tick()
            self.assertEqual(rig.resting(), [("sell", D("104.10"), D("1"))])
            self.assertEqual(rig.job.state.reason, "catch_up")
            rig.fill("sell", "104.10")
            rig.set_position("9")
            await rig.tick()
        rt = rig.job.state.runtime
        self.assertFalse(rt.catching)
        self.assertEqual((rt.book.level, rt.book.lean, rt.core), (1, D("-1"), D("10")))
        self.assertEqual(
            rig.resting(),
            [
                ("buy", D("96.67"), D("1")),
                ("buy", D("100.00"), D("1")),
                ("sell", D("106.67"), D("1")),
                ("sell", D("110.00"), D("1")),
            ],
        )

    async def test_the_catch_up_follows_the_touch(self) -> None:
        """MS13: when the ask moves, the catch-up comes off and goes back on at the new ask."""
        rig = Rig(bid="104", ask="104.10")
        with rig.patch():
            await rig.start()
            await rig.tick(2)
            rig.gateway.set_book("104.20", "104.30")
            await rig.tick()
        self.assertEqual(rig.resting(), [("sell", D("104.30"), D("1"))])
        self.assertGreaterEqual(len(rig.orders.cancels), 1)


class LatticeTests(MassagerJobCase):
    async def test_a_round_trip_moves_the_level_and_captures_one_step(self) -> None:
        """MS9, MS10: sold at 103.33, bought back at 100.00, the Lean is 0 and 3.33 captured."""
        rig = Rig()
        with rig.patch():
            await rig.start()
            await rig.tick()
            rig.fill("sell", "103.33")
            rig.set_position("9")
            rig.gateway.set_book("103.20", "103.30")
            await rig.tick()
            self.assertEqual(rig.job.state.runtime.book.level, 1)
            self.assertEqual(
                rig.resting(),
                [
                    ("buy", D("96.67"), D("1")),
                    ("buy", D("100.00"), D("1")),
                    ("sell", D("106.67"), D("1")),
                    ("sell", D("110.00"), D("1")),
                ],
            )
            rig.fill("buy", "100.00")
            rig.set_position("10")
            rig.gateway.set_book("99.90", "100")
            await rig.tick()
        rt = rig.job.state.runtime
        self.assertEqual((rt.book.level, rt.book.lean), (0, D("0")))
        self.assertEqual(rt.book.captured, D("3.33"))
        self.assertEqual(rt.core, D("10"))
        self.assertEqual(rig.job.snapshot()["captured_pnl"], "3.33")

    async def test_a_partial_fill_keeps_the_level(self) -> None:
        """MS9: 0.4 filled at level −1 adds to the Lean but does not move the lattice."""
        rig = Rig()
        with rig.patch():
            await rig.start()
            await rig.tick()
            rig.fill("buy", "96.67", remaining="0.6")
            rig.set_position("10.4")
            await rig.tick()
        rt = rig.job.state.runtime
        self.assertEqual((rt.book.level, rt.book.lean), (0, D("0.4")))
        self.assertEqual(rt.book.level_fills, {-1: D("0.4")})
        self.assertIn(("buy", D("96.67"), D("0.6")), rig.resting())
        self.assertEqual(rt.core, D("10"))

    async def test_a_level_that_would_cross_waits(self) -> None:
        """MS14: price ran past level +2, so that sell is not sent until it would rest."""
        rig = Rig()
        with rig.patch():
            await rig.start()
            await rig.tick()
            rig.fill("sell", "103.33")
            rig.set_position("9")
            rig.gateway.set_book("108", "108.10")
            await rig.tick()
            sells = [r for r in rig.resting() if r[0] == "sell"]
            self.assertEqual(sells, [("sell", D("110.00"), D("1"))])
            rig.gateway.set_book("106", "106.10")
            await rig.tick()
        self.assertIn(("sell", D("106.67"), D("1")), rig.resting())


class OutsideFillTests(MassagerJobCase):
    async def test_an_outside_add_moves_the_core_and_its_entry(self) -> None:
        """MS11, MS12, MS15: a Ladder adds 5; once it has held 3 s the Core is 15."""
        rig = Rig()
        with rig.patch():
            await rig.start()
            await rig.tick(1)
            rig.set_position("15")
            await rig.job._evaluate()
            self.assertEqual(rig.job.state.runtime.core, D("10"))
            rig.clock.advance(OUTSIDE_GRACE_MS)
            await rig.job._evaluate()
        rt = rig.job.state.runtime
        self.assertEqual(rt.core, D("15"))
        self.assertEqual(rt.core_entry, (D("98") * 10 + D("100.05") * 5) / 15)
        self.assertEqual(rig.job.state.status, ChaseStatus.RUNNING)

    async def test_its_own_fill_seen_early_is_not_an_outside_fill(self) -> None:
        """MS15: the Position shows the fill before the order row does; the Core does not move."""
        rig = Rig()
        with rig.patch():
            await rig.start()
            await rig.tick()
            rig.set_position("9")
            await rig.job._evaluate()
            rig.clock.advance(OUTSIDE_GRACE_MS // 2)
            rig.fill("sell", "103.33")
            await rig.tick(2)
        rt = rig.job.state.runtime
        self.assertEqual((rt.core, rt.core_entry), (D("10"), D("98")))
        self.assertIsNone(rt.pending_core)

    async def test_an_outside_close_stops_it(self) -> None:
        """MS12: the Position closed by hand ends the Massager and pulls its Clips."""
        rig = Rig()
        with rig.patch():
            await rig.start()
            await rig.tick()
            rig.set_position("0")
            await rig.tick(3)
        self.assertEqual(rig.job.state.status, ChaseStatus.STOPPED)
        self.assertEqual(rig.job.state.reason, "position_closed")
        self.assertEqual(rig.resting(), [])

    async def test_a_core_shrunk_to_the_swing_pauses_it(self) -> None:
        """MS12: a hand close down to 3 leaves a Core no larger than the Swing."""
        rig = Rig()
        with rig.patch():
            await rig.start()
            await rig.tick()
            rig.set_position("3")
            await rig.tick(3)
        self.assertEqual(rig.job.state.status, ChaseStatus.PAUSED)
        self.assertEqual(rig.job.state.reason, "core_within_swing")
        self.assertEqual(rig.resting(), [])


class RestartTests(MassagerJobCase):
    async def test_a_run_comes_back_with_its_lean_level_and_core(self) -> None:
        """MS16."""
        rig = Rig()
        with rig.patch():
            await rig.start()
            await rig.tick()
            rig.fill("sell", "103.33")
            rig.set_position("9")
            rig.gateway.set_book("103.20", "103.30")
            await rig.tick()
            row = {**rig.job.snapshot(), **rig.job.state.ledger.to_persist()}
            again = MassagerRunner(rig.book)
            again.hydrate_from_row(row)
        self.assertEqual(again.state.runtime.to_json(), rig.job.state.runtime.to_json())
        self.assertEqual(again.state.params, rig.job.state.params)
        self.assertEqual(again.state.params.clip, D("1"))  # type: ignore[union-attr]
        self.assertEqual(again.state.status, ChaseStatus.RUNNING)
        self.assertEqual(again.snapshot()["captured_pnl"], rig.job.snapshot()["captured_pnl"])
