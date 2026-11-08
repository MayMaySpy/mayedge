"""Massager planner: docs/massager-rules.md MS1–MS12, MS22."""

from __future__ import annotations

import unittest
from dataclasses import replace
from decimal import Decimal

from mayedge.algos.massager.plan import (
    Book,
    MassagerParams,
    MassagerRefused,
    Tally,
    Venue,
    basis,
    carry,
    catch_up,
    check_start,
    core,
    core_entry_after,
    fee_floor,
    judge,
    lattice,
    live_step,
    resting,
    should_redraw,
    start_anchor,
    tally_from_run,
)

D = Decimal
LIT = Venue(tick=D("0.0001"), size_step=D("1"), min_qty=D("10"))
# The run check_start makes of ASK: 3 levels each side, Clip 100.
PARAMS = MassagerParams(
    band_low=D("3.20"), band_high=D("3.50"), swing=D("300"), step=D("0.05"), clip=D("100")
)
ASK = replace(PARAMS, clip=D("0"))


def ask(**kw: object) -> MassagerParams:
    return replace(ASK, **kw)  # type: ignore[arg-type]


def start(p: MassagerParams = ASK, position: str = "1000", mid: str = "3.42", venue: Venue = LIT):
    return check_start(p, position=D(position), mid=D(mid), venue=venue)


class StartTests(unittest.TestCase):
    def _refused(
        self,
        rule: str,
        p: MassagerParams,
        *,
        position: str = "1000",
        mid: str = "3.42",
        venue: Venue = LIT,
    ) -> None:
        with self.assertRaises(MassagerRefused) as ctx:
            start(p, position, mid, venue)
        self.assertEqual(ctx.exception.rule, rule)

    def test_no_position_is_refused(self) -> None:
        self._refused("MS1", ASK, position="0")

    def test_the_band_must_hold_the_price(self) -> None:
        self._refused("MS2", ask(band_low=D("3.50"), band_high=D("3.20")))
        self._refused("MS2", ASK, mid="3.51")
        self._refused("MS2", ASK, mid="3.19")
        start(mid="3.50")

    def test_the_step_sets_the_levels_and_the_clip(self) -> None:
        run, grid = start()
        self.assertEqual(run, PARAMS)
        self.assertEqual(grid.levels, 3)
        # A tighter Step: 7 levels (0.15 ÷ 0.02, rounded down), Clip 300 ÷ 7 down to 42.
        run, grid = start(ask(step=D("0.02")))
        self.assertEqual((grid.levels, run.clip, run.swing), (7, D("42"), D("294")))
        self._refused("MS3", ask(step=D("0")))
        self._refused("MS3", ask(swing=D("0")))

    def test_a_step_wider_than_half_the_band_is_refused(self) -> None:
        self._refused("MS3", ask(step=D("0.16")))
        run, _ = start(ask(step=D("0.15")))
        self.assertEqual((run.levels, run.clip), (1, D("300")))

    def test_a_clip_under_the_minimum_is_refused(self) -> None:
        # 0.15 ÷ 0.005 is 30 levels, so a Swing of 270 is a Clip of 9, under 10.
        self._refused("MS3", ask(step=D("0.005"), swing=D("270")))
        run, _ = start(ask(step=D("0.005"), swing=D("300")))
        self.assertEqual(run.clip, D("10"))

    def test_the_swing_is_whole_clips(self) -> None:
        run, _ = start(ask(swing=D("250")))
        self.assertEqual((run.clip, run.swing), (D("83"), D("249")))
        self.assertEqual(run.swing / run.clip, run.levels)

    def test_a_swing_as_large_as_the_core_is_refused(self) -> None:
        self._refused("MS4", ASK, position="300")
        self._refused("MS4", ASK, position="-300")
        start(position="-301")

    def test_levels_step_out_from_the_center(self) -> None:
        _, grid = start()
        self.assertEqual(grid.center, D("3.35"))
        self.assertEqual(grid.step, D("0.05"))
        self.assertEqual(
            list(grid.prices),
            [D(x) for x in ("3.20", "3.25", "3.30", "3.35", "3.40", "3.45", "3.50")],
        )

    def test_a_step_that_does_not_fit_the_band_stays_inside_it(self) -> None:
        _, grid = start(ask(step=D("0.04")))
        self.assertEqual(
            list(grid.prices),
            [D(x) for x in ("3.23", "3.27", "3.31", "3.35", "3.39", "3.43", "3.47")],
        )

    def test_levels_round_to_the_nearest_tick(self) -> None:
        p = replace(PARAMS, band_low=D("3.20"), band_high=D("3.30"), step=D("0.05") / 3)
        grid = lattice(p, D("0.01"))
        # Step 0.01666…: 3.2333 rounds to 3.23, 3.2667 to 3.27.
        self.assertEqual(
            list(grid.prices),
            [D(x) for x in ("3.20", "3.22", "3.23", "3.25", "3.27", "3.28", "3.30")],
        )

    def test_a_step_that_does_not_clear_fees_is_refused(self) -> None:
        # Center 3.35 × 2 × 80 bps = 0.0536 + tick > Step 0.05.
        self._refused(
            "MS6",
            ASK,
            venue=Venue(tick=LIT.tick, size_step=D("1"), min_qty=D("10"), maker_bps=D("80")),
        )
        start(venue=Venue(tick=LIT.tick, size_step=D("1"), min_qty=D("10"), maker_bps=D("2")))

    def test_a_run_kept_before_the_step_was_typed_reads_back(self) -> None:
        raw = PARAMS.to_json()
        del raw["step"]
        self.assertEqual(MassagerParams.from_json(raw), PARAMS)


def rest(level: int, p: MassagerParams = PARAMS, anchor: Decimal | None = None, step=None):
    """MS9: what rests from a level, the anchor at its start price unless given."""
    return resting(
        p,
        level=level,
        anchor=start_anchor(p, level) if anchor is None else anchor,
        step=p.step if step is None else step,
        tick=LIT.tick,
    )


class LatticeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.grid = lattice(PARAMS, LIT.tick)

    def test_the_catch_up_owes_the_levels_passed(self) -> None:
        up = catch_up(self.grid, PARAMS, D("3.42"))
        self.assertEqual((up.level, up.side, up.qty), (1, "sell", D("100")))
        on = catch_up(self.grid, PARAMS, D("3.45"))
        self.assertEqual((on.level, on.side, on.qty), (2, "sell", D("200")))
        down = catch_up(self.grid, PARAMS, D("3.21"))
        self.assertEqual((down.level, down.side, down.qty), (-2, "buy", D("200")))
        edge = catch_up(self.grid, PARAMS, D("3.20"))
        self.assertEqual((edge.level, edge.qty), (-3, D("300")))

    def test_no_catch_up_at_the_center(self) -> None:
        for mid in ("3.35", "3.39", "3.31"):
            c = catch_up(self.grid, PARAMS, D(mid))
            self.assertEqual((c.level, c.side, c.qty), (0, None, D("0")), mid)

    def test_two_levels_rest_each_side(self) -> None:
        orders = rest(1)
        self.assertEqual(
            [(o.level, o.side, o.price, o.qty) for o in orders],
            [
                (2, "sell", D("3.4500"), D("100")),
                (3, "sell", D("3.5000"), D("100")),
                (0, "buy", D("3.3500"), D("100")),
                (-1, "buy", D("3.3000"), D("100")),
            ],
        )

    def test_the_edge_rests_only_inward(self) -> None:
        top = rest(3)
        self.assertEqual([(o.level, o.side) for o in top], [(2, "buy"), (1, "buy")])
        near = rest(-2)
        self.assertEqual(
            [(o.level, o.side) for o in near], [(-1, "sell"), (0, "sell"), (-3, "buy")]
        )

    def test_a_full_fill_moves_the_level(self) -> None:
        book = Book(level=1)
        self.assertFalse(book.level_fill(0, D("40"), PARAMS.clip))
        self.assertEqual(book.level, 1)
        self.assertTrue(book.level_fill(0, D("60"), PARAMS.clip))
        self.assertEqual(book.level, 0)
        self.assertEqual(book.level_fills, {})
        self.assertEqual([o.level for o in rest(book.level)], [1, 2, -1, -2])

    def test_a_partly_filled_level_rests_what_is_left(self) -> None:
        book = Book(level=1)
        book.fill("buy", D("40"), D("3.35"))
        book.level_fill(0, D("40"), PARAMS.clip)
        buy0 = next(o for o in rest(1) if o.level == 0)
        self.assertEqual(book.qty_for(buy0, PARAMS.swing), D("60"))

    def test_no_order_takes_the_lean_past_the_swing(self) -> None:
        book = Book(level=-2, lean=D("250"))
        buy = next(o for o in rest(-2) if o.level == -3)
        self.assertEqual(book.qty_for(buy, PARAMS.swing), D("50"))
        sell = next(o for o in rest(-2) if o.level == -1)
        self.assertEqual(book.qty_for(sell, PARAMS.swing), D("100"))

    def test_the_massager_pnl_marks_the_lean_at_the_mid(self) -> None:
        """MS10: Captured 5 and a Lean of +100 at 3.30 marked at 3.25 is 5 − 5 = 0."""
        book = Book(level=-1, lean=D("100"), lean_price=D("3.30"), captured=D("5"))
        self.assertEqual(book.marked(D("3.25")), D("0"))
        self.assertEqual(Book(captured=D("5")).marked(D("3.25")), D("5"))
        short = Book(lean=D("-100"), lean_price=D("3.40"), captured=D("5"))
        self.assertEqual(short.marked(D("3.35")), D("10"))

    def test_the_book_round_trips(self) -> None:
        book = Book(level=-1, lean=D("100"), lean_price=D("3.3"), captured=D("5"))
        book.level_fills[-2] = D("30")
        self.assertEqual(Book.from_json(book.to_json()), book)
        self.assertEqual(MassagerParams.from_json(PARAMS.to_json()), PARAMS)

    def test_a_short_core_also_sells_above_the_center(self) -> None:
        """MS7: a short holder sells high too, so its Position grows as price rises."""
        _, grid = start(position="-1000")
        c = catch_up(grid, PARAMS, D("3.42"))
        self.assertEqual((c.side, c.qty), ("sell", D("100")))
        book = Book()
        book.fill("sell", c.qty, D("3.42"))
        self.assertEqual(D("-1000") + book.lean, D("-1100"))
        self.assertEqual(core(D("-1100"), book.lean), D("-1000"))

    def test_levels_step_from_the_anchor(self) -> None:
        """MS9: a buy filled at 3.33 with a 0.05 Step: next sells 3.38 and 3.43, buys below."""
        orders = rest(-1, anchor=D("3.33"))
        self.assertEqual(
            [(o.level, o.side, o.price) for o in orders],
            [
                (0, "sell", D("3.3800")),
                (1, "sell", D("3.4300")),
                (-2, "buy", D("3.2800")),
                (-3, "buy", D("3.2300")),
            ],
        )
        wide = rest(-1, anchor=D("3.33"), step=D("0.10"))
        self.assertEqual(
            [o.price for o in wide if o.side == "sell"], [D("3.4300")]
        )  # 3.53 is past the Band

    def test_nothing_rests_outside_the_band(self) -> None:
        orders = rest(1, anchor=D("3.45"), step=D("0.04"))
        self.assertEqual(
            [(o.side, o.price) for o in orders],
            [("sell", D("3.4900")), ("buy", D("3.4100")), ("buy", D("3.3700"))],
        )

    def test_the_live_step_is_kept_between_the_fee_floor_and_half_the_band(self) -> None:
        p = replace(PARAMS, step_mode="atr", atr_mult=D("0.5"))
        floor = fee_floor(p.center, D("2"), LIT.tick)
        self.assertEqual(floor, D("3.35") * 2 * 2 / 10000 + D("0.0001"))
        self.assertEqual(live_step(D("0.08"), p, floor=floor), D("0.04"))
        self.assertEqual(live_step(D("1"), p, floor=floor), D("0.15"))
        self.assertEqual(live_step(D("0.0001"), p, floor=floor), floor)

    def test_a_small_atr_move_does_not_redraw(self) -> None:
        self.assertFalse(should_redraw(D("0.05"), D("0.0599")))
        self.assertFalse(should_redraw(D("0.05"), D("0.0401")))
        self.assertTrue(should_redraw(D("0.05"), D("0.06")))
        self.assertTrue(should_redraw(D("0.05"), D("0.04")))


class CountTests(unittest.TestCase):
    def test_a_round_trip_captures_one_step(self) -> None:
        book = Book()
        book.fill("sell", D("100"), D("3.40"), fee=D("0.01"))
        book.fill("buy", D("100"), D("3.35"), fee=D("0.01"))
        self.assertEqual(book.lean, D("0"))
        self.assertIsNone(book.lean_price)
        self.assertEqual(book.captured, D("4.98"))

    def test_a_long_lean_round_trip_captures_one_step(self) -> None:
        book = Book()
        book.fill("buy", D("100"), D("3.30"))
        book.fill("buy", D("100"), D("3.25"))
        book.fill("sell", D("100"), D("3.30"))
        self.assertEqual(book.lean, D("100"))
        self.assertEqual(book.lean_price, D("3.275"))
        self.assertEqual(book.captured, D("2.5"))

    def test_a_fill_through_zero_opens_the_rest(self) -> None:
        book = Book()
        book.fill("buy", D("100"), D("3.30"))
        book.fill("sell", D("300"), D("3.40"))
        self.assertEqual(book.lean, D("-200"))
        self.assertEqual(book.lean_price, D("3.40"))
        self.assertEqual(book.captured, D("10"))

    def test_basis_takes_captured_off_the_core_entry(self) -> None:
        self.assertEqual(basis(D("3.36"), D("1000"), D("5")), D("3.355"))
        self.assertEqual(basis(D("3.36"), D("-1000"), D("5")), D("3.365"))
        self.assertIsNone(basis(D("3.36"), D("0"), D("5")))

    def test_an_outside_add_moves_the_core_entry(self) -> None:
        self.assertEqual(core_entry_after(D("3.36"), D("1000"), D("1000"), D("3.20")), D("3.28"))
        self.assertEqual(core_entry_after(D("3.36"), D("1000"), D("-300"), D("3.50")), D("3.36"))
        self.assertEqual(core_entry_after(D("3.36"), D("-1000"), D("-1000"), D("3.40")), D("3.38"))


class OutsideFillTests(unittest.TestCase):
    def test_an_outside_close_stops_it(self) -> None:
        self.assertEqual(judge(D("0"), D("-100"), core_side=1, swing=D("300")), "stop")
        self.assertEqual(judge(D("-50"), D("100"), core_side=1, swing=D("300")), "stop")

    def test_a_core_shrunk_to_the_swing_pauses_it(self) -> None:
        # Position 400 with Lean +100 after a hand close: Core 300, no larger than the Swing.
        self.assertEqual(judge(D("400"), D("100"), core_side=1, swing=D("300")), "pause")
        self.assertEqual(judge(D("-350"), D("-50"), core_side=-1, swing=D("300")), "pause")

    def test_an_outside_add_keeps_it_running(self) -> None:
        self.assertEqual(core(D("1300"), D("100")), D("1200"))
        self.assertEqual(judge(D("1300"), D("100"), core_side=1, swing=D("300")), "run")
        self.assertEqual(judge(D("-1300"), D("-100"), core_side=-1, swing=D("300")), "run")


if __name__ == "__main__":
    unittest.main()


class AtrTests(unittest.TestCase):
    def test_atr_reads_closed_candles_only(self) -> None:
        """MS21: the open candle's range does not count until it closes."""
        from mayedge.algos.massager.atr import closed_atr
        from mayedge.lighter.models import Candle

        hour = 3600
        bars = [
            Candle(time=i * hour, open=3.2, high=3.3, low=3.2, close=3.25, volume=1)
            for i in range(20)
        ]
        now_ms = 20 * hour * 1000 + 1  # bar 19 closed a moment ago
        atr = closed_atr(bars, "1h", now_ms)
        assert atr is not None
        self.assertAlmostEqual(float(atr), 0.1, places=9)
        wild = [*bars, Candle(time=20 * hour, open=3.25, high=4.0, low=3.0, close=3.5, volume=1)]
        self.assertEqual(closed_atr(wild, "1h", now_ms), atr)
        self.assertIsNone(closed_atr(bars[:10], "1h", now_ms))


class TallyTests(unittest.TestCase):
    """MS11: Basis is the Tally's cost over the Position."""

    def test_basis_counts_every_massager_trade(self) -> None:
        """The example: 1,000 at 3.36, sell 100 at 3.40, buy back at 3.35, then three sells."""
        t = Tally.begin(D("1000"), D("3.36"), since=1)
        t.massager_fill("sell", D("100"), D("3.40"), D("0"))
        t.massager_fill("buy", D("100"), D("3.35"), D("0"))
        self.assertEqual(t.basis(), D("3.355"))
        for px in ("3.40", "3.45", "3.50"):
            t.massager_fill("sell", D("100"), D(px), D("0"))
        self.assertEqual((t.size, t.cost), (D("700"), D("2320")))
        self.assertEqual(t.entry, D("3.36"))

    def test_a_fee_raises_a_longs_basis(self) -> None:
        t = Tally.begin(D("1000"), D("3"), since=1)
        t.massager_fill("sell", D("100"), D("3"), D("1"))
        t.massager_fill("buy", D("100"), D("3"), D("1"))
        self.assertEqual(t.basis(), D("3.002"))

    def test_basis_of_a_short_rises_with_a_round_trip(self) -> None:
        t = Tally.begin(D("-1000"), D("3.36"), since=1)
        t.massager_fill("sell", D("100"), D("3.40"), D("0"))
        t.massager_fill("buy", D("100"), D("3.35"), D("0"))
        self.assertEqual(t.basis(), D("3.365"))

    def test_an_outside_add_moves_basis_at_the_mid(self) -> None:
        t = Tally.begin(D("1000"), D("3.36"), since=1)
        t.massager_fill("sell", D("100"), D("3.46"), D("0"))  # cost 3,014 for 900
        t.outside(D("100"), D("3.20"))
        self.assertEqual((t.size, t.cost), (D("1000"), D("3334")))
        self.assertEqual(t.entry, (D("3.36") * 900 + D("3.20") * 100) / 1000)

    def test_an_outside_reduction_keeps_basis(self) -> None:
        t = Tally.begin(D("1000"), D("3.36"), since=1)
        t.massager_fill("sell", D("100"), D("3.46"), D("0"))
        before = t.basis()
        t.outside(D("-450"), D("9.99"))
        self.assertEqual(t.size, D("450"))
        self.assertEqual(t.basis(), before)
        self.assertEqual(t.entry, D("3.36"))

    def test_the_tally_round_trips(self) -> None:
        t = Tally(D("5"), D("15"), D("3"), D("2"), 3, 9, D("5"), D("3.1"))
        self.assertEqual(Tally.from_json(t.to_json()), t)

    def test_a_run_kept_before_the_tally_builds_one(self) -> None:
        """MS16: Core 1,000 at 3.36, Captured 5, Lean −100 at 3.40."""
        book = Book(lean=D("-100"), lean_price=D("3.40"), captured=D("5"))
        t = tally_from_run(core_size=D("1000"), core_entry=D("3.36"), book=book, since=7)
        self.assertEqual((t.size, t.cost, t.runs, t.since), (D("900"), D("3015"), 1, 7))


def ended(size: str = "700", entry: str = "3.40", cost: str = "2320") -> Tally:
    """A run's Tally that last saw the venue at ``size`` and ``entry``."""
    return Tally(
        size=D(size),
        cost=D(cost),
        entry=D("3.36"),
        captured_before=D("4"),
        runs=1,
        since=1,
        venue_size=D(size),
        venue_entry=D(entry),
    )


class CarryTests(unittest.TestCase):
    """MS22: the Tally a new run takes."""

    def take(self, last: Tally | None, position: str, entry: str | None, **kw: object):
        return carry(
            last,
            last_captured=D("5"),
            source="MS-0001",
            position=D(position),
            entry=D(entry) if entry else None,
            mid=D("3.60"),
            since=50,
            **kw,  # type: ignore[arg-type]
        )

    def test_a_new_run_carries_the_tally(self) -> None:
        took = self.take(ended(), "700", "3.40")
        self.assertTrue(took.carried)
        self.assertEqual(took.source, "MS-0001")
        self.assertEqual((took.tally.cost, took.tally.size), (D("2320"), D("700")))
        self.assertEqual((took.tally.captured_before, took.tally.runs), (D("9"), 2))
        self.assertIsNone(took.tally.venue_size)

    def test_a_fresh_start_begins_a_new_tally(self) -> None:
        took = self.take(ended(), "700", "3.40", fresh=True)
        self.assertFalse(took.carried)
        self.assertEqual((took.tally.cost, took.tally.runs), (D("2380"), 1))
        self.assertEqual(took.tally.captured_before, D("0"))
        self.assertEqual(took.why, "Started fresh")

    def test_no_run_begins_at_the_mid_without_an_entry(self) -> None:
        took = self.take(None, "700", None)
        self.assertFalse(took.carried)
        self.assertEqual(took.tally.basis(), D("3.60"))

    def test_a_closed_position_does_not_carry(self) -> None:
        self.assertFalse(self.take(ended(), "700", "3.40", last_closed=True).carried)

    def test_the_other_side_does_not_carry(self) -> None:
        took = self.take(ended(), "-700", "3.40")
        self.assertFalse(took.carried)
        self.assertEqual(took.why, "The Position is on the other side")

    def test_a_reduction_between_runs_carries_at_basis(self) -> None:
        took = self.take(ended(), "350", "3.40")
        self.assertTrue(took.carried)
        self.assertEqual((took.tally.size, took.tally.cost), (D("350"), D("1160")))

    def test_an_add_between_runs_carries_at_the_implied_price(self) -> None:
        """700 at 3.40, now 1,000 at 3.43: the 300 added came in at 3.50."""
        took = self.take(ended(), "1000", "3.43")
        self.assertTrue(took.carried)
        self.assertEqual((took.tally.size, took.tally.cost), (D("1000"), D("3370")))

    def test_a_reopened_position_does_not_carry(self) -> None:
        self.assertFalse(self.take(ended(), "700", "3.10").carried)
        self.assertFalse(self.take(ended(), "350", "3.10").carried)
        # An add whose implied price is far from the mid is a Position opened again.
        self.assertFalse(self.take(ended(), "710", "4.10").carried)

    def test_a_run_without_the_venue_carries_only_to_the_same_size(self) -> None:
        last = replace(ended(), venue_size=None, venue_entry=None)
        self.assertTrue(self.take(last, "700", "3.10").carried)
        self.assertFalse(self.take(last, "800", "3.10").carried)

    def test_the_band_reads_the_last_closed_candle(self) -> None:
        """MS23: the open candle's close does not count until it closes."""
        from mayedge.algos.massager.atr import last_close
        from mayedge.lighter.models import Candle

        hour = 3600
        bars = [
            Candle(time=i * hour, open=3.2, high=3.3, low=3.2, close=3.2 + i / 100, volume=1)
            for i in range(3)
        ]
        self.assertEqual(last_close(bars, "1h", 3 * hour * 1000 - 1), (2 * hour * 1000, D("3.21")))
        self.assertEqual(last_close(bars, "1h", 3 * hour * 1000), (3 * hour * 1000, D("3.22")))
        self.assertIsNone(last_close(bars[:1], "1h", hour * 1000 - 1))
