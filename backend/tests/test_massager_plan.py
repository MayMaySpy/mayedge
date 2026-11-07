"""Massager planner: docs/massager-rules.md MS1–MS12."""

from __future__ import annotations

import unittest
from decimal import Decimal

from mayedge.algos.massager.plan import (
    Book,
    MassagerParams,
    MassagerRefused,
    Venue,
    basis,
    catch_up,
    check_start,
    core,
    core_entry_after,
    judge,
    lattice,
    resting,
)

D = Decimal
LIT = Venue(tick=D("0.0001"), size_step=D("1"), min_qty=D("10"))
PARAMS = MassagerParams(band_low=D("3.20"), band_high=D("3.50"), swing=D("300"), clip=D("100"))


def params(**kw: object) -> MassagerParams:
    base: dict[str, object] = {
        "band_low": PARAMS.band_low,
        "band_high": PARAMS.band_high,
        "swing": PARAMS.swing,
        "clip": PARAMS.clip,
    }
    base.update(kw)
    return MassagerParams(**base)  # type: ignore[arg-type]


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
            check_start(p, position=D(position), mid=D(mid), venue=venue)
        self.assertEqual(ctx.exception.rule, rule)

    def test_no_position_is_refused(self) -> None:
        self._refused("MS1", PARAMS, position="0")

    def test_the_band_must_hold_the_price(self) -> None:
        self._refused("MS2", params(band_low=D("3.50"), band_high=D("3.20")))
        self._refused("MS2", PARAMS, mid="3.51")
        self._refused("MS2", PARAMS, mid="3.19")
        check_start(PARAMS, position=D("1000"), mid=D("3.50"), venue=LIT)

    def test_swing_must_be_whole_clips(self) -> None:
        self._refused("MS3", params(swing=D("250")))
        self._refused("MS3", params(clip=D("0")))

    def test_a_clip_under_the_minimum_is_refused(self) -> None:
        self._refused("MS3", params(swing=D("8"), clip=D("4")))
        self._refused("MS3", params(swing=D("301.5"), clip=D("100.5")))

    def test_a_swing_as_large_as_the_core_is_refused(self) -> None:
        self._refused("MS4", PARAMS, position="300")
        self._refused("MS4", PARAMS, position="-300")
        check_start(PARAMS, position=D("-301"), mid=D("3.42"), venue=LIT)

    def test_levels_split_the_band_evenly(self) -> None:
        grid = check_start(PARAMS, position=D("1000"), mid=D("3.42"), venue=LIT)
        self.assertEqual(grid.levels, 3)
        self.assertEqual(grid.center, D("3.35"))
        self.assertEqual(grid.step, D("0.05"))
        self.assertEqual(
            list(grid.prices),
            [D(x) for x in ("3.20", "3.25", "3.30", "3.35", "3.40", "3.45", "3.50")],
        )

    def test_levels_round_to_the_nearest_tick(self) -> None:
        grid = lattice(params(band_low=D("3.20"), band_high=D("3.30"), swing=D("300")), D("0.01"))
        # Step 0.01666…: 3.2333 rounds to 3.23, 3.2667 to 3.27.
        self.assertEqual(
            list(grid.prices),
            [D(x) for x in ("3.20", "3.22", "3.23", "3.25", "3.27", "3.28", "3.30")],
        )

    def test_a_step_that_does_not_clear_fees_is_refused(self) -> None:
        # Center 3.35 × 2 × 80 bps = 0.0536 + tick > Step 0.05.
        self._refused(
            "MS6",
            PARAMS,
            venue=Venue(tick=LIT.tick, size_step=D("1"), min_qty=D("10"), maker_bps=D("80")),
        )
        check_start(
            PARAMS,
            position=D("1000"),
            mid=D("3.42"),
            venue=Venue(tick=LIT.tick, size_step=D("1"), min_qty=D("10"), maker_bps=D("2")),
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
        orders = resting(self.grid, PARAMS, 1)
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
        top = resting(self.grid, PARAMS, 3)
        self.assertEqual([(o.level, o.side) for o in top], [(2, "buy"), (1, "buy")])
        near = resting(self.grid, PARAMS, -2)
        self.assertEqual(
            [(o.level, o.side) for o in near], [(-1, "sell"), (0, "sell"), (-3, "buy")]
        )

    def test_a_full_fill_moves_the_level(self) -> None:
        book = Book(level=1)
        book.fill("buy", D("40"), D("3.35"))
        self.assertEqual(book.level, 1)
        book.fill("buy", D("60"), D("3.35"))
        book.level_filled(0)
        self.assertEqual([o.level for o in resting(self.grid, PARAMS, book.level)], [1, 2, -1, -2])

    def test_a_short_core_also_sells_above_the_center(self) -> None:
        """MS7: a short holder sells high too, so its Position grows as price rises."""
        grid = check_start(PARAMS, position=D("-1000"), mid=D("3.42"), venue=LIT)
        c = catch_up(grid, PARAMS, D("3.42"))
        self.assertEqual((c.side, c.qty), ("sell", D("100")))
        book = Book()
        book.fill("sell", c.qty, D("3.42"))
        self.assertEqual(D("-1000") + book.lean, D("-1100"))
        self.assertEqual(core(D("-1100"), book.lean), D("-1000"))


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
