"""Massager job on the harness fakes: docs/massager-rules.md MS8–MS23."""

from __future__ import annotations

import asyncio
import contextlib
import sys
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from mayedge import db as store
from mayedge import persist_algo
from mayedge.algos.chase.state import ChaseStatus
from mayedge.algos.massager.book import MassagerBook
from mayedge.algos.massager.config import OUTSIDE_GRACE_MS, is_massager_client_order
from mayedge.algos.massager.job import MassagerRunner
from mayedge.algos.massager.plan import MassagerParams, MassagerRefused
from mayedge.config import settings

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


# An ATR run: ½ × ATR on 1h. ATR 8 makes a Step of 4, 2 levels each side, Clip 1.5.
ATR_PARAMS = MassagerParams(
    band_low=D("90"),
    band_high=D("110"),
    swing=D("3"),
    step=D("0"),
    step_mode="atr",
    atr_mult=D("0.5"),
    atr_tf="1h",
)
HOUR_MS = 3_600_000


class Rig:
    def __init__(self, *, bid: str = "100", ask: str = "100.10", position: str = "10") -> None:
        self.atr: Decimal | None = D("8")
        self.atr_reads: list[str] = []
        # MS23: the last closed 1h candle the desk would read, as (close time ms, close).
        self.close: tuple[int, Decimal] | None = None
        self.close_reads = 0
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
        self.job = MassagerRunner(self.book, self.read_atr, self.read_close)

    async def read_close(self, market_index: int, timeframe: str) -> tuple[int, Decimal] | None:
        self.close_reads += 1
        return self.close

    async def read_atr(self, market_index: int, timeframe: str) -> Decimal | None:
        self.atr_reads.append(timeframe)
        return self.atr

    def patch(self) -> Any:
        return patch_grid(self.clock, self.gateway, self.orders)

    async def start(self, params: MassagerParams = PARAMS, **kw: Any) -> None:
        await self.job.start(algo_id="MS-0001", market_index=1, params=params, **kw)
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

    def set_position(self, size: str, entry: str = "98") -> None:
        self.orders.positions = (
            [] if size == "0" else [{"market_index": 1, "size": size, "entry_price": entry}]
        )

    def keep_as_stopped(self, algo_id: str = "MS-0001", reason: str | None = None) -> None:
        """Store the run as the book does when it ends, in the test's own database."""
        snap = {**self.job.snapshot(), "algo_id": algo_id, "status": "stopped", "reason": reason}
        ledger = self.job.state.ledger.to_persist()
        persist_algo.upsert_run(
            snap,
            next_clip=ledger["next_clip"],
            next_fill=ledger["next_fill"],
            trade_ids=ledger["trade_ids"],
            trade_qty_by_clip=ledger["trade_qty_by_clip"],
            clips=ledger["clips"],
            fills=ledger["fills"],
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


class TrimTests(MassagerJobCase):
    async def test_old_closed_clips_are_dropped_once_counted(self) -> None:
        """MS16: past the last 50 closed Clips, one closed 10 minutes and counted goes."""
        rig = Rig()
        with rig.patch():
            await rig.start()
            await rig.tick()
            ledger = rig.job.state.ledger
            rt = rig.job.state.runtime
            live = {c.seq for c in ledger.live_clips()}
            now = rig.clock.now_ms
            for i in range(60):
                c = ledger.place(
                    client_order_index=13_500_000_000 + i,
                    price=D("99"),
                    qty=D("1"),
                    now=now,
                    side="buy",
                )
                c.status = "cancelled"
                c.closed_at = now
                rt.clip_levels[c.seq] = -1
            uncounted = ledger.clips[-60]
            ledger._fill(uncounted, D("1"), now)
            rig.job._trim_ledger()
            self.assertEqual(sum(c.status != "live" for c in ledger.clips), 60)
            rig.clock.advance(600_000)
            rig.job._trim_ledger()
        closed = [c for c in ledger.clips if c.status != "live"]
        # 50 kept, plus the one whose fill is not counted yet.
        self.assertEqual(len(closed), 51)
        self.assertIn(uncounted, closed)
        self.assertTrue(live <= {c.seq for c in ledger.clips})
        kept = {c.seq for c in ledger.clips}
        self.assertTrue(all(f.clip_seq in kept for f in ledger.fills))
        self.assertTrue(set(rt.clip_levels) <= kept)


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


class LiveStepTests(MassagerJobCase):
    async def test_an_atr_run_starts_at_k_times_atr(self) -> None:
        """MS3, MS21: ½ × ATR 8 is a Step of 4: two levels each side of 100, Clip 1.5."""
        rig = Rig()
        with rig.patch():
            await rig.start(ATR_PARAMS)
            await rig.tick()
        params = rig.job.state.params
        assert params is not None
        self.assertEqual((params.step, params.clip, params.swing), (D("4"), D("1.5"), D("3")))
        self.assertEqual(
            rig.resting(),
            [
                ("buy", D("92.00"), D("1.5")),
                ("buy", D("96.00"), D("1.5")),
                ("sell", D("104.00"), D("1.5")),
                ("sell", D("108.00"), D("1.5")),
            ],
        )
        snap = rig.job.snapshot()
        self.assertEqual((snap["step"], snap["atr"], snap["atr_tf"]), ("4", "8", "1h"))

    async def test_no_atr_no_start(self) -> None:
        rig = Rig()
        rig.atr = None
        with rig.patch(), self.assertRaises(MassagerRefused) as ctx:
            await rig.start(ATR_PARAMS)
        self.assertEqual(ctx.exception.rule, "MS3")
        self.assertEqual(rig.orders.creates, [])

    async def test_a_small_atr_move_keeps_the_levels(self) -> None:
        """MS21: ATR 8 → 8.5 is a Step 6% off, under 20%: nothing moves."""
        rig = Rig()
        with rig.patch():
            await rig.start(ATR_PARAMS)
            await rig.tick()
            before = rig.resting()
            reads = len(rig.atr_reads)
            rig.atr = D("8.5")
            rig.clock.advance(HOUR_MS)
            await rig.tick()
        self.assertGreater(len(rig.atr_reads), reads)
        self.assertEqual(rig.resting(), before)
        self.assertEqual(rig.job.state.runtime.step, D("4"))
        self.assertEqual(rig.job.state.runtime.atr, D("8.5"))

    async def test_an_atr_run_redraws_around_the_anchor(self) -> None:
        """MS9, MS21: sold at 104, then ATR 10 makes the Step 5: the buy-back rests at 99."""
        rig = Rig()
        with rig.patch():
            await rig.start(ATR_PARAMS)
            await rig.tick()
            rig.fill("sell", "104.00")
            rig.set_position("8.5")
            rig.gateway.set_book("103.90", "104")
            await rig.tick()
            self.assertEqual(rig.job.state.runtime.anchor, D("104"))
            rig.atr = D("10")
            rig.clock.advance(HOUR_MS)
            await rig.tick()
        rt = rig.job.state.runtime
        self.assertEqual((rt.step, rt.book.level), (D("5"), 1))
        self.assertEqual(
            rig.resting(),
            [
                ("buy", D("94.00"), D("1.5")),
                ("buy", D("99.00"), D("1.5")),
                ("sell", D("109.00"), D("1.5")),
            ],
        )

    async def test_a_fixed_run_never_reads_atr(self) -> None:
        rig = Rig()
        with rig.patch():
            await rig.start()
            rig.clock.advance(HOUR_MS * 2)
            await rig.tick()
        self.assertEqual(rig.atr_reads, [])


async def round_trip(rig: Rig) -> None:
    """Start at 100, sell a Clip at 103.33 and buy it back at 100: Captured 3.33."""
    await rig.start()
    await rig.tick()
    rig.fill("sell", "103.33")
    rig.set_position("9")
    rig.gateway.set_book("103.20", "103.30")
    await rig.tick()
    rig.fill("buy", "100.00")
    rig.set_position("10")
    rig.gateway.set_book("99.90", "100")
    await rig.tick()


class TallyTests(MassagerJobCase):
    def setUp(self) -> None:
        self._td = TemporaryDirectory()
        self._path = patch.object(settings, "db_path", str(Path(self._td.name) / "mayedge.db"))
        self._path.start()
        # The class keeps the store off disk; these tests read their own runs back.
        self._read = patch("mayedge.db.load_last_run", persist_algo.load_last_run)
        self._read.start()
        store.close_db()
        store.init_db()

    def tearDown(self) -> None:
        store.close_db()
        self._read.stop()
        self._path.stop()
        self._td.cleanup()

    async def test_the_tally_counts_its_fills_and_shows_basis(self) -> None:
        """MS11: 10 at 98, a round trip of 3.33: Basis 98 − 0.333."""
        rig = Rig()
        with rig.patch():
            await round_trip(rig)
        snap = rig.job.snapshot()
        self.assertEqual(snap["captured_pnl"], "3.33")
        self.assertEqual(snap["basis"], "97.667")
        self.assertEqual((snap["core_entry"], snap["tally_runs"]), ("98", 1))
        self.assertEqual(snap["tally_captured"], "3.33")
        tally = rig.job.state.runtime.tally
        assert tally is not None
        self.assertEqual((tally.venue_size, tally.venue_entry), (D("10"), D("98")))

    async def test_an_outside_add_moves_basis_at_the_mid(self) -> None:
        """MS11, MS15: a Ladder adds 5 at the mid 100.05."""
        rig = Rig()
        with rig.patch():
            await rig.start()
            await rig.tick(1)
            rig.set_position("15")
            await rig.job._evaluate()
            rig.clock.advance(OUTSIDE_GRACE_MS)
            await rig.job._evaluate()
        tally = rig.job.state.runtime.tally
        assert tally is not None
        self.assertEqual((tally.size, tally.cost), (D("15"), D("980") + D("100.05") * 5))

    async def test_start_carries_the_last_runs_tally(self) -> None:
        """MS22: the next run on the Market takes the Tally the last one left."""
        first = Rig()
        with first.patch():
            await round_trip(first)
            first.keep_as_stopped("MS-0001")
        second = Rig()
        last = second.book.last_run(1)
        assert last is not None
        with second.patch():
            await second.job.start(algo_id="MS-0002", market_index=1, params=PARAMS, last=last)
        snap = second.job.snapshot()
        self.assertTrue(snap["carried"])
        self.assertEqual(snap["carried_from"], "MS-0001")
        self.assertEqual((snap["basis"], snap["tally_runs"]), ("97.667", 2))
        self.assertEqual((snap["tally_captured"], snap["captured_pnl"]), ("3.33", "0"))

    async def test_a_fresh_start_does_not_carry(self) -> None:
        first = Rig()
        with first.patch():
            await round_trip(first)
            first.keep_as_stopped("MS-0001")
        second = Rig()
        last = second.book.last_run(1)
        with second.patch():
            await second.job.start(
                algo_id="MS-0002", market_index=1, params=PARAMS, last=last, fresh=True
            )
        snap = second.job.snapshot()
        self.assertFalse(snap["carried"])
        self.assertEqual(
            (snap["basis"], snap["tally_runs"], snap["carry_why"]), ("98", 1, "Started fresh")
        )

    async def test_the_carry_preview_says_what_a_start_would_take(self) -> None:
        first = Rig()
        with first.patch():
            await round_trip(first)
            first.keep_as_stopped("MS-0001")
        preview = first.book.carry_preview(1)
        self.assertEqual(
            preview,
            {
                "carried": True,
                "why": "Carried",
                "source": "MS-0001",
                "basis": "97.667",
                "entry": "98",
                "captured": "3.33",
                "runs": 2,
            },
        )

    async def test_a_run_kept_before_the_tally_builds_one(self) -> None:
        """MS16: a stored run with no Tally reads back with one built from its Core."""
        rig = Rig()
        with rig.patch():
            await round_trip(rig)
            row = {**rig.job.snapshot(), **rig.job.state.ledger.to_persist()}
            row["params_json"]["runtime"].pop("tally")
            again = MassagerRunner(rig.book)
            again.hydrate_from_row(row)
        self.assertEqual(again.snapshot()["basis"], "97.667")
        tally = again.state.runtime.tally
        assert tally is not None
        self.assertEqual((tally.size, tally.runs), (D("10"), 1))

    async def test_the_chop_reading_is_kept_with_the_run(self) -> None:
        """MS24."""
        rig = Rig()
        chop = {
            "label": "ranging",
            "er": "0.21",
            "band_low": "95",
            "band_high": "105",
            "tf": "1h",
            "n": 24,
        }
        with rig.patch():
            await rig.start(chop=chop)
            row = {**rig.job.snapshot(), **rig.job.state.ledger.to_persist()}
            again = MassagerRunner(rig.book)
            again.hydrate_from_row(row)
        self.assertEqual(again.snapshot()["chop"], chop)


class BandTests(MassagerJobCase):
    """MS23: a 1h close outside the Band pauses it."""

    async def at_the_close(self, rig: Rig, close: str) -> None:
        await rig.start()
        await rig.tick()
        rig.close = (3_600_000, D(close))
        rig.clock.now_ms = 3_605_000
        await rig.tick(1)

    async def test_a_close_above_the_band_pauses_it(self) -> None:
        rig = Rig()
        with rig.patch():
            await self.at_the_close(rig, "110.50")
        self.assertEqual(rig.job.state.status, ChaseStatus.PAUSED)
        self.assertEqual(rig.resting(), [])
        snap = rig.job.snapshot()
        self.assertEqual(
            (snap["reason"], snap["band_side"], snap["band_close"]), ("left_band", "above", "110.5")
        )
        self.assertEqual(snap["lean"], "0")

    async def test_a_close_below_the_band_pauses_it(self) -> None:
        rig = Rig()
        with rig.patch():
            await self.at_the_close(rig, "89.99")
        self.assertEqual(rig.job.snapshot()["band_side"], "below")
        self.assertEqual(rig.job.state.status, ChaseStatus.PAUSED)

    async def test_a_close_inside_keeps_it_running(self) -> None:
        """A wick past the Band that closes inside does not pause it."""
        rig = Rig()
        with rig.patch():
            await self.at_the_close(rig, "109.99")
        self.assertEqual(rig.job.state.status, ChaseStatus.RUNNING)
        self.assertEqual(len(rig.resting()), 4)

    async def test_a_band_check_reads_once_per_close(self) -> None:
        rig = Rig()
        with rig.patch():
            await self.at_the_close(rig, "100")
            await rig.tick(4)
        self.assertEqual(rig.close_reads, 1)

    async def test_a_failed_band_read_tries_again(self) -> None:
        rig = Rig()
        with rig.patch():
            await rig.start()
            rig.clock.now_ms = 3_605_000
            await rig.tick(1)
            self.assertEqual(rig.close_reads, 1)
            rig.close = (3_600_000, D("120"))
            await rig.tick(3)
            self.assertEqual(rig.close_reads, 1)
            rig.clock.advance(60_000)
            await rig.tick(1)
        self.assertEqual(rig.close_reads, 2)
        self.assertEqual(rig.job.state.status, ChaseStatus.PAUSED)

    async def test_resume_does_not_pause_again_on_the_same_close(self) -> None:
        rig = Rig()
        with rig.patch():
            await self.at_the_close(rig, "120")
            rig.job.state.runtime.band_next_at = 0
            await rig.job.unpause()
            task, rig.job._task = rig.job._task, None
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            await rig.tick(1)
        self.assertEqual(rig.job.state.status, ChaseStatus.RUNNING)
