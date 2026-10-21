"""Trail engine math. Rule ids are docs/trail-rules.md."""

from __future__ import annotations

import unittest
from dataclasses import replace
from decimal import Decimal as D

from mayedge.algos.trail.engine import (
    Follow,
    Point,
    backstop,
    crossed,
    follow,
    move_due,
    step,
    trigger_at,
)

# A long exit (closing side sell) on ZRO, the example in trail-rules.md.
LONG_EXIT = Follow(
    side="sell",
    distance=D("1.5"),
    distance_kind="pct",
    tick=D("0.0001"),
    activation=D("2.25"),
    floor=D("2.0854"),
)


def _run(f: Follow, prices: list[str], point: Point | None = None) -> Point:
    p = point or Point()
    for px in prices:
        p = follow(f, p, D(px))
    return p


class FollowTests(unittest.TestCase):
    def test_the_zro_example(self) -> None:
        p = _run(LONG_EXIT, ["2.2"])
        self.assertFalse(p.active)
        self.assertEqual(p.trigger, D("2.0854"))
        p = _run(LONG_EXIT, ["2.25"], p)
        self.assertTrue(p.active)
        self.assertEqual(p.trigger, D("2.2162"))
        self.assertFalse(
            move_due(
                LONG_EXIT,
                venue=D("2.2162"),
                wanted=trigger_at(LONG_EXIT, D("2.252")),
                best=D("2.252"),
                now_ms=10_000,
                last_move_ms=0,
            )
        )
        p = _run(LONG_EXIT, ["2.26"], p)
        self.assertEqual(p.trigger, D("2.2261"))
        self.assertTrue(
            move_due(
                LONG_EXIT,
                venue=D("2.2162"),
                wanted=D("2.2261"),
                best=D("2.26"),
                now_ms=10_000,
                last_move_ms=0,
            )
        )
        self.assertTrue(crossed(LONG_EXIT, D("2.2261"), D("2.2261")))

    def test_best_price_follows_the_favourable_side(self) -> None:
        f = replace(LONG_EXIT, activation=None, floor=None)
        self.assertEqual(_run(f, ["10", "12", "11"]).best, D("12"))
        entry = replace(f, side="buy")
        self.assertEqual(_run(entry, ["10", "8", "9"]).best, D("8"))

    def test_trigger_sits_the_distance_behind_the_best_price(self) -> None:
        f = Follow(side="sell", distance=D("1"), distance_kind="price", tick=D("0.01"))
        self.assertEqual(_run(f, ["100"]).trigger, D("99"))
        short_exit = replace(f, side="buy")
        self.assertEqual(_run(short_exit, ["100"]).trigger, D("101"))
        pct = Follow(side="sell", distance=D("2"), distance_kind="pct", tick=D("0.01"))
        self.assertEqual(_run(pct, ["200"]).trigger, D("196"))

    def test_trigger_rounds_away_from_the_best_price(self) -> None:
        f = Follow(side="sell", distance=D("1"), distance_kind="pct", tick=D("0.01"))
        # 101.23 × 0.99 = 100.2177: a sell trigger rounds down.
        self.assertEqual(trigger_at(f, D("101.23")), D("100.21"))
        # 101.23 × 1.01 = 102.2423: a buy trigger rounds up.
        self.assertEqual(trigger_at(replace(f, side="buy"), D("101.23")), D("102.25"))

    def test_trigger_never_moves_back(self) -> None:
        f = Follow(side="sell", distance=D("1"), distance_kind="price", tick=D("0.01"))
        p = _run(f, ["100", "105", "101"])
        self.assertEqual(p.trigger, D("104"))
        # A wider distance later does not loosen it either (F4).
        wider = replace(f, distance=D("3"))
        self.assertEqual(follow(wider, p, D("101")).trigger, D("104"))

    def test_activation_waits_for_its_price(self) -> None:
        entry = Follow(
            side="buy", distance=D("1"), distance_kind="price", tick=D("0.01"), activation=D("95")
        )
        p = _run(entry, ["100", "96"])
        self.assertFalse(p.active)
        self.assertIsNone(p.trigger)
        p = _run(entry, ["95", "93"], p)
        self.assertTrue(p.active)
        self.assertEqual(p.best, D("93"))
        self.assertEqual(p.trigger, D("94"))
        self.assertTrue(crossed(entry, D("94"), D("94.5")))
        self.assertFalse(crossed(entry, D("94"), D("93.5")))

    def test_the_stop_holds_until_activation(self) -> None:
        p = _run(LONG_EXIT, ["2.1", "2.24"])
        self.assertEqual(p.trigger, D("2.0854"))
        # After activation the floor still holds when the trail sits below it.
        low = replace(LONG_EXIT, distance=D("20"))
        self.assertEqual(_run(low, ["2.3"]).trigger, D("2.0854"))


class StepTests(unittest.TestCase):
    def test_a_move_smaller_than_the_step_is_not_sent(self) -> None:
        f = Follow(side="sell", distance=D("1"), distance_kind="price", tick=D("0.01"))
        self.assertEqual(step(f, D("100")), D("0.1"))
        self.assertFalse(
            move_due(
                f, venue=D("99"), wanted=D("99.09"), best=D("100.09"), now_ms=0, last_move_ms=None
            )
        )
        self.assertTrue(
            move_due(
                f, venue=D("99"), wanted=D("99.1"), best=D("100.1"), now_ms=0, last_move_ms=None
            )
        )

    def test_the_step_is_at_least_two_ticks(self) -> None:
        f = Follow(side="sell", distance=D("0.05"), distance_kind="price", tick=D("0.01"))
        self.assertEqual(step(f, D("100")), D("0.02"))

    def test_moves_wait_the_min_gap(self) -> None:
        f = Follow(side="sell", distance=D("1"), distance_kind="price", tick=D("0.01"))
        kw = {"venue": D("99"), "wanted": D("100"), "best": D("101")}
        self.assertFalse(move_due(f, **kw, now_ms=4_999, last_move_ms=0))
        self.assertTrue(move_due(f, **kw, now_ms=5_000, last_move_ms=0))

    def test_a_move_back_is_never_due(self) -> None:
        f = Follow(side="sell", distance=D("1"), distance_kind="price", tick=D("0.01"))
        self.assertFalse(
            move_due(f, venue=D("99"), wanted=D("98"), best=D("99"), now_ms=0, last_move_ms=None)
        )

    def test_the_backstop_sits_one_step_behind(self) -> None:
        f = Follow(side="sell", distance=D("1"), distance_kind="price", tick=D("0.01"))
        self.assertEqual(backstop(f, D("99"), D("100")), D("98.9"))
        self.assertEqual(backstop(replace(f, side="buy"), D("101"), D("100")), D("101.1"))


if __name__ == "__main__":
    unittest.main()
