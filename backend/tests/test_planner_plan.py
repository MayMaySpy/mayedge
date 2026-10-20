from __future__ import annotations

import unittest
from dataclasses import replace
from decimal import Decimal as D
from typing import Any

from mayedge.algos.ladder.plan import build_rungs
from mayedge.algos.planner.plan import (
    EntryChase,
    EntryLadder,
    MarketContext,
    Plan,
    PlannerParams,
    PlanRefused,
    Target,
    breakeven_price,
    build_plan,
    price_plan,
    resize_targets,
)

ZRO = MarketContext(
    tick=D("0.00001"),
    qty_step=D("1"),
    min_qty=D("5"),
    mark=D("2.19082"),
    equity=D("5537"),
    min_base=D("5"),
)


BASE = PlannerParams(
    mode="enter",
    side="buy",
    stop=D("2.0854"),
    targets=[Target("r", D("2"), D("50")), Target("r", D("3"), D("50"))],
    entry_type="limit",
    entry_price=D("2.19082"),
    size=D("100"),
)


def _enter(**kw: Any) -> PlannerParams:
    return replace(BASE, **kw)


def _ctx(**kw: Any) -> MarketContext:
    return replace(ZRO, **kw)


class PlanMathTests(unittest.TestCase):
    def test_the_zro_example(self) -> None:
        plan = build_plan(_enter(), ZRO)
        self.assertEqual(plan.r, D("0.10542"))
        self.assertEqual([t.price for t in plan.targets], [D("2.40166"), D("2.50708")])
        self.assertEqual(plan.risk_usd.quantize(D("0.01")), D("10.54"))
        assert plan.risk_pct is not None
        self.assertEqual(plan.risk_pct.quantize(D("0.01")), D("0.19"))

    def test_size_from_risk_rounds_down_to_the_lot(self) -> None:
        plan = build_plan(_enter(size=None, risk_pct=D("1")), ZRO)
        self.assertEqual(plan.size, D("525"))

    def test_size_from_risk_pays_the_taker_fee_at_the_stop(self) -> None:
        ctx = _ctx(taker_bps=D("5"))
        plan = build_plan(_enter(size=None, risk_pct=D("1")), ctx)
        # 55.37 / (0.10542 + 2.0854 * 0.0005) = 520.08
        self.assertEqual(plan.size, D("520"))

    def test_r_targets_reprice_from_the_actual_entry(self) -> None:
        plan = price_plan(
            side="buy",
            entry=D("2.2"),
            stop=D("2.1"),
            size=D("100"),
            targets=[Target("r", D("2"), D("50")), Target("price", D("2.5"), D("50"))],
            ctx=ZRO,
        )
        self.assertEqual([t.price for t in plan.targets], [D("2.4"), D("2.5")])

    def test_targets_are_ordered_nearest_entry_first(self) -> None:
        plan = build_plan(
            _enter(targets=[Target("r", D("3"), D("30")), Target("r", D("1"), D("70"))]), ZRO
        )
        self.assertEqual([t.index for t in plan.targets], [1, 2])
        self.assertLess(plan.targets[0].price, plan.targets[1].price)
        self.assertEqual(plan.targets[0].pct, D("70"))

    def test_what_no_target_closes_is_the_runner(self) -> None:
        plan = build_plan(
            _enter(targets=[Target("r", D("2"), D("33")), Target("r", D("3"), D("33"))]), ZRO
        )
        self.assertEqual([t.qty for t in plan.targets], [D("33"), D("33")])
        self.assertEqual(plan.runner, D("34"))

    def test_the_last_target_takes_the_rounding_not_the_runner(self) -> None:
        plan = build_plan(
            _enter(
                size=D("101"),
                targets=[Target("r", D("1"), D("50")), Target("r", D("2"), D("50"))],
            ),
            ZRO,
        )
        self.assertEqual([t.qty for t in plan.targets], [D("50"), D("51")])
        self.assertEqual(plan.runner, D("0"))

    def test_a_small_target_joins_the_next_one(self) -> None:
        plan = build_plan(
            _enter(
                size=D("20"),
                targets=[Target("r", D("1"), D("10")), Target("r", D("2"), D("90"))],
            ),
            ZRO,
        )
        self.assertEqual(len(plan.targets), 1)
        self.assertEqual(plan.targets[0].qty, D("20"))
        self.assertEqual(plan.targets[0].pct, D("100"))
        self.assertTrue(plan.warnings)

    def test_a_small_last_target_joins_the_one_before(self) -> None:
        plan = build_plan(
            _enter(
                size=D("20"),
                targets=[Target("r", D("1"), D("80")), Target("r", D("2"), D("20"))],
            ),
            ZRO,
        )
        self.assertEqual([t.qty for t in plan.targets], [D("20")])
        self.assertEqual(plan.targets[0].r, D("1"))

    def test_prices_round_to_the_tick_the_safe_way(self) -> None:
        ctx = _ctx(tick=D("0.01"), mark=D("100"))
        long = build_plan(
            _enter(
                stop=D("95.555"),
                entry_price=D("100"),
                targets=[Target("price", D("110.009"), D("100"))],
            ),
            ctx,
        )
        self.assertEqual(long.stop, D("95.55"))
        self.assertEqual(long.targets[0].price, D("110.00"))
        short = build_plan(
            _enter(
                side="sell",
                stop=D("104.441"),
                entry_price=D("100"),
                targets=[Target("price", D("90.001"), D("100"))],
            ),
            ctx,
        )
        self.assertEqual(short.stop, D("104.45"))
        self.assertEqual(short.targets[0].price, D("90.01"))

    def test_breakeven_covers_the_round_trip_fee(self) -> None:
        self.assertEqual(
            breakeven_price("buy", D("100"), taker_bps=D("5"), tick=D("0.01")), D("100.10")
        )
        self.assertEqual(
            breakeven_price("sell", D("100"), taker_bps=D("5"), tick=D("0.01")), D("99.90")
        )
        self.assertEqual(breakeven_price("buy", D("2.19082"), taker_bps=D("0"), tick=D("0.00001")), D("2.19082"))

    def test_percentages_are_from_entry(self) -> None:
        plan = build_plan(_enter(), ZRO)
        self.assertEqual(plan.stop_pct.quantize(D("0.01")), D("-4.81"))
        self.assertEqual(plan.targets[0].move_pct.quantize(D("0.01")), D("9.62"))


class StopStepTests(unittest.TestCase):
    def _steps(self, mode: str, pcts: list[str]) -> list[tuple[int, D, str]]:
        targets = [Target("r", D(str(i + 1)), D(p)) for i, p in enumerate(pcts)]
        plan = price_plan(
            side="buy",
            entry=D("100"),
            stop=D("95"),
            size=D("100"),
            targets=targets,
            ctx=_ctx(tick=D("0.01"), mark=D("100")),
            stop_steps=mode,  # type: ignore[arg-type]
        )
        return [(s.after, s.price, s.to) for s in plan.steps]

    def test_breakeven_is_one_step_after_tp1(self) -> None:
        self.assertEqual(self._steps("breakeven", ["50", "50"]), [(1, D("100"), "breakeven")])

    def test_step_up_steps_to_the_target_before(self) -> None:
        self.assertEqual(
            self._steps("ladder", ["40", "40", "20"]),
            [(1, D("100"), "breakeven"), (2, D("105"), "tp1")],
        )

    def test_a_runner_keeps_the_last_step(self) -> None:
        self.assertEqual(
            self._steps("ladder", ["40", "40"]),
            [(1, D("100"), "breakeven"), (2, D("105"), "tp1")],
        )

    def test_no_step_after_which_nothing_is_left(self) -> None:
        self.assertEqual(self._steps("ladder", ["100"]), [])
        self.assertEqual(self._steps("off", ["50", "50"]), [])

    def test_a_row_from_before_steps_reads_its_breakeven_flag(self) -> None:
        raw = _enter().to_json()
        raw.pop("stop_steps")
        self.assertEqual(PlannerParams.from_json({**raw, "breakeven": True}).stop_steps, "breakeven")
        self.assertEqual(PlannerParams.from_json({**raw, "breakeven": False}).stop_steps, "off")


class PlanRefusalTests(unittest.TestCase):
    def _refused(self, params: PlannerParams, ctx: MarketContext = ZRO) -> str:
        with self.assertRaises(PlanRefused) as caught:
            build_plan(params, ctx)
        return caught.exception.rule

    def test_a_stop_on_the_winning_side_is_refused(self) -> None:
        self.assertEqual(self._refused(_enter(stop=D("2.3"))), "S1")

    def test_a_stop_mark_has_passed_is_refused(self) -> None:
        ctx = _ctx(mark=D("2.08"))
        self.assertEqual(self._refused(_enter(), ctx), "S1")

    def test_a_target_behind_entry_is_refused(self) -> None:
        self.assertEqual(
            self._refused(_enter(targets=[Target("price", D("2.1"), D("100"))])), "S1"
        )

    def test_a_stop_beyond_the_liquidation_price_is_refused(self) -> None:
        ctx = _ctx(liq_price=D("2.1"))
        self.assertEqual(self._refused(_enter(), ctx), "S2")

    def test_enter_refuses_with_a_position_open(self) -> None:
        ctx = _ctx(position_size=D("10"), position_entry=D("2.1"))
        self.assertEqual(self._refused(_enter(), ctx), "S3")

    def test_attach_refuses_without_a_position(self) -> None:
        self.assertEqual(self._refused(_enter(mode="attach", size=None)), "S4")

    def test_attach_takes_the_positions_entry_and_size(self) -> None:
        ctx = _ctx(position_size=D("100"), position_entry=D("2.19082"))
        plan = build_plan(_enter(mode="attach", size=None, entry_price=None), ctx)
        self.assertEqual(plan.size, D("100"))
        self.assertEqual(plan.entry, D("2.19082"))

    def test_attach_refuses_the_other_side(self) -> None:
        ctx = _ctx(position_size=D("-100"), position_entry=D("2.19082"))
        self.assertEqual(self._refused(_enter(mode="attach", size=None), ctx), "S4")

    def test_targets_over_100_pct_are_refused(self) -> None:
        self.assertEqual(
            self._refused(
                _enter(targets=[Target("r", D("2"), D("60")), Target("r", D("3"), D("50"))])
            ),
            "P5",
        )

    def test_no_target_is_refused(self) -> None:
        self.assertEqual(self._refused(_enter(targets=[])), "P5")

    def test_a_size_too_small_for_any_target_is_refused(self) -> None:
        self.assertEqual(
            self._refused(_enter(size=D("8"), targets=[Target("r", D("2"), D("50"))])), "P7"
        )

    def test_size_and_risk_together_are_refused(self) -> None:
        self.assertEqual(self._refused(_enter(risk_pct=D("1"))), "P2")


class TargetOrderTests(unittest.TestCase):
    def test_targets_are_limits_unless_picked(self) -> None:
        plan = build_plan(
            _enter(targets=[Target("r", D("2"), D("50")), Target("r", D("3"), D("50"), "trigger")]),
            ZRO,
        )
        self.assertEqual([t.order for t in plan.targets], ["limit", "trigger"])

    def test_a_joined_target_keeps_the_type_of_the_one_it_joins(self) -> None:
        plan = build_plan(
            _enter(
                size=D("20"),
                targets=[Target("r", D("1"), D("10"), "limit"), Target("r", D("2"), D("90"), "trigger")],
            ),
            ZRO,
        )
        self.assertEqual([(t.qty, t.order) for t in plan.targets], [(D("20"), "trigger")])

    def test_a_target_without_a_type_is_a_trigger(self) -> None:
        self.assertEqual(Target.from_json({"kind": "r", "value": "2", "pct": "50"}).order, "trigger")
        self.assertEqual(
            Target.from_json({"kind": "r", "value": "2", "pct": "50", "order": "limit"}).order, "limit"
        )
        with self.assertRaises(PlanRefused):
            Target.from_json({"kind": "r", "value": "2", "pct": "50", "order": "market"})


class ParamsJsonTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        params = _enter(risk_pct=None, expiry_min=30, slippage=0.02)
        again = PlannerParams.from_json(params.to_json())
        self.assertEqual(again, params)

    def test_slippage_is_capped_at_five_pct(self) -> None:
        raw = _enter().to_json() | {"slippage": 0.5}
        self.assertEqual(PlannerParams.from_json(raw).slippage, 0.05)


if __name__ == "__main__":
    unittest.main()


class ChaseEntryTests(unittest.TestCase):
    def _chase(self, **kw: Any) -> PlannerParams:
        band = EntryChase(low=D("2.15"), high=D("2.2"))
        return _enter(entry_type="chase", entry_price=None, entry_chase=band, **kw)

    def test_a_chase_entry_is_sized_from_the_worst_fill_in_its_band(self) -> None:
        plan = build_plan(self._chase(size=None, risk_pct=D("1")), ZRO)
        self.assertEqual(plan.entry, D("2.2"))
        # 55.37 ÷ (2.2 − 2.0854) = 483.1, against 525 for a Limit at 2.19082.
        self.assertEqual(plan.size, D("483"))
        assert plan.risk_pct is not None
        self.assertLessEqual(plan.risk_pct, D("1"))

    def test_a_stop_inside_the_chase_band_is_refused(self) -> None:
        with self.assertRaises(PlanRefused) as e:
            build_plan(self._chase(stop=D("2.16")), _ctx(mark=D("2.18")))
        self.assertEqual(e.exception.rule, "E11")
        short = self._chase(side="sell", stop=D("2.19"), targets=[Target("r", D("2"), D("100"))])
        with self.assertRaises(PlanRefused) as e:
            build_plan(short, _ctx(mark=D("2.17")))
        self.assertEqual(e.exception.rule, "E11")

    def test_a_chase_band_with_its_low_over_its_high_is_refused(self) -> None:
        with self.assertRaises(PlanRefused) as e:
            PlannerParams.from_json(
                {"side": "buy", "stop": "1", "entry_type": "chase",
                 "entry_chase": {"low": "2.2", "high": "2.1"}, "targets": []}
            )
        self.assertEqual(e.exception.rule, "E11")

    def test_a_chase_entry_survives_a_save(self) -> None:
        params = self._chase(size=D("10"))
        again = PlannerParams.from_json(params.to_json())
        self.assertEqual(again.entry_chase, params.entry_chase)


class LadderEntryTests(unittest.TestCase):
    def _ladder(self, rungs: int = 5, strength: str = "0", **kw: Any) -> PlannerParams:
        ladder = EntryLadder(price_from=D("2.19"), price_to=D("2.15"), rungs=rungs, strength=D(strength))
        return _enter(entry_type="ladder", entry_price=None, entry_ladder=ladder, **kw)

    @staticmethod
    def _loss_at_stop(plan: Any, ctx: MarketContext) -> D:
        fee = plan.stop * ctx.taker_bps / D("10000")
        return sum((r.qty * (abs(r.price - plan.stop) + fee) for r in plan.rungs), D("0"))

    def test_a_ladder_entry_rests_its_rungs_like_the_ladder_algo(self) -> None:
        plan = build_plan(self._ladder(strength="1"), ZRO)
        # Strength high: 3:1 from the high rung to the low one.
        self.assertEqual([r.price for r in plan.rungs], [D("2.19"), D("2.18"), D("2.17"), D("2.16"), D("2.15")])
        self.assertEqual([r.qty for r in plan.rungs], [D("30"), D("25"), D("20"), D("15"), D("10")])
        same = build_rungs(
            side="buy", qty=D("100"), price_from=D("2.19"), price_to=D("2.15"), rungs=5,
            tick=ZRO.tick, qty_step=ZRO.qty_step, min_qty=ZRO.min_qty, size_skew=D("1"),
        )
        self.assertEqual(list(plan.rungs), same)
        # Either way round: a buy ladder runs down from its higher price.
        flipped = replace(self._ladder(strength="1"), entry_ladder=EntryLadder(D("2.15"), D("2.19"), 5, D("1")))
        self.assertEqual(build_plan(flipped, ZRO).rungs, plan.rungs)

    def test_a_ladder_entry_is_sized_so_every_rung_filling_loses_the_risk(self) -> None:
        plan = build_plan(self._ladder(size=None, risk_pct=D("1")), ZRO)
        # Drawn from the average with every rung filled (EL2), R 2.17 − 2.0854.
        self.assertEqual(plan.entry, D("2.17"))
        # 55.37 ÷ 0.0846 = 654.5: every rung filled loses at most 1%, one lot more would not.
        self.assertEqual(plan.size, D("654"))
        self.assertEqual(sum((r.qty for r in plan.rungs), D("0")), D("654"))
        self.assertLessEqual(self._loss_at_stop(plan, ZRO), D("55.37"))
        self.assertGreater(D("655") * (plan.entry - plan.stop), D("55.37"))
        # Fewer rungs filling loses less.
        self.assertLess(self._loss_at_stop(replace(plan, rungs=plan.rungs[:2]), ZRO), D("55.37"))
        # With the taker fee at the stop, on a skewed ladder.
        fee = _ctx(taker_bps=D("5"))
        skewed = build_plan(self._ladder(strength="-1", size=None, risk_pct=D("1")), fee)
        self.assertEqual(skewed.entry, D("2.165"))
        self.assertLessEqual(self._loss_at_stop(skewed, fee), D("55.37"))
        per_unit = skewed.r + skewed.stop * D("5") / D("10000")
        self.assertLessEqual(skewed.size * per_unit, D("55.37"))
        self.assertGreater((skewed.size + 1) * per_unit, D("55.37"))

    def test_a_stop_inside_the_ladder_is_refused(self) -> None:
        with self.assertRaises(PlanRefused) as e:
            build_plan(self._ladder(stop=D("2.16")), ZRO)
        self.assertEqual(e.exception.rule, "EL2")
        short = self._ladder(side="sell", stop=D("2.18"), targets=[Target("r", D("2"), D("100"))])
        with self.assertRaises(PlanRefused) as e:
            build_plan(short, _ctx(mark=D("2.14")))
        self.assertEqual(e.exception.rule, "EL2")

    def test_a_ladder_that_would_not_fit_the_open_order_limits_is_refused(self) -> None:
        for rungs in (1, 21):
            with self.assertRaises(PlanRefused) as e:
                build_plan(self._ladder(rungs=rungs), ZRO)
            self.assertEqual(e.exception.rule, "EL4")
        twenty = self._ladder(rungs=20, size=D("200"), stop=D("2.1"))
        self.assertEqual(len(build_plan(twenty, _ctx(resting_orders=10)).rungs), 20)
        with self.assertRaises(PlanRefused) as e:
            build_plan(twenty, _ctx(resting_orders=11))
        self.assertEqual(e.exception.rule, "EL4")

    def test_a_ladder_rung_under_the_venue_minimum_is_refused(self) -> None:
        with self.assertRaises(PlanRefused) as e:
            build_plan(self._ladder(size=D("20")), ZRO)
        self.assertEqual(e.exception.rule, "EL1")

    def test_a_ladder_rung_must_meet_the_quote_minimum_at_its_own_price(self) -> None:
        # MON: $10 minimum. 1500 a rung clears it at mark 0.02 (500) but not near 0.005 (2000).
        mon = MarketContext(
            tick=D("0.00001"), qty_step=D("0.1"), min_qty=D("500"), mark=D("0.01999"),
            equity=D("5537"), min_base=D("250"), min_quote=D("10"),
        )
        ladder = EntryLadder(price_from=D("0.01"), price_to=D("0.005"), rungs=20, strength=D("0"))
        params = _enter(
            entry_type="ladder", entry_price=None, entry_ladder=ladder, stop=D("0.004"), size=D("30000"),
            targets=[Target("price", D("0.03"), D("100"))],
        )
        with self.assertRaises(PlanRefused) as e:
            build_plan(params, mon)
        self.assertEqual(e.exception.rule, "EL1")
        self.assertIn("$10 minimum", e.exception.message)
        plan = build_plan(replace(params, size=D("80000")), mon)
        self.assertTrue(all(r.qty * r.price >= D("10") for r in plan.rungs))

    def test_a_ladder_entry_survives_a_save(self) -> None:
        params = self._ladder(strength="-1")
        again = PlannerParams.from_json(params.to_json())
        self.assertEqual(again.entry_ladder, params.entry_ladder)
        plan = build_plan(params, ZRO)
        self.assertEqual(Plan.from_json(plan.to_json()).rungs, plan.rungs)
        with self.assertRaises(PlanRefused) as e:
            PlannerParams.from_json(
                {"side": "buy", "stop": "1", "entry_type": "ladder",
                 "entry_ladder": {"price_from": "2", "price_to": "2", "rungs": 5}, "targets": []}
            )
        self.assertEqual(e.exception.rule, "EL1")


class ResizeTests(unittest.TestCase):
    """M6: an outside close resizes what each target has left. P10: each target's $."""

    def _plan(self, size: str, *pcts: str) -> Plan:
        targets = [Target("r", D(str(i + 2)), D(pct)) for i, pct in enumerate(pcts)]
        return build_plan(_enter(size=D(size), targets=targets), ZRO)

    def test_an_outside_close_keeps_each_targets_share(self) -> None:
        plan = self._plan("1000", "50", "30")
        resized, warnings = resize_targets(
            plan, filled={}, expected=D("1000"), held=D("300"), stop_steps="breakeven", ctx=ZRO
        )
        self.assertEqual([t.qty for t in resized.targets], [D("150"), D("90")])
        self.assertEqual(resized.runner, D("60"))
        self.assertEqual(resized.size, D("300"))
        self.assertEqual(resized.risk_usd, plan.risk_usd * D("0.3"))
        self.assertEqual([t.price for t in resized.targets], [t.price for t in plan.targets])
        self.assertEqual(warnings, [])

    def test_a_filled_target_stays_and_the_rest_resize(self) -> None:
        plan = self._plan("1000", "50", "30")
        resized, _ = resize_targets(
            plan, filled={1: D("500")}, expected=D("500"), held=D("250"), stop_steps="breakeven", ctx=ZRO
        )
        self.assertEqual([t.qty for t in resized.targets], [D("500"), D("150")])
        self.assertEqual(resized.runner, D("100"))
        self.assertEqual(resized.size, D("750"))
        self.assertEqual([s.after for s in resized.steps], [1])

    def test_a_resized_target_under_the_minimum_joins_the_next_and_takes_its_step(self) -> None:
        plan = self._plan("100", "10", "60")
        self.assertEqual([s.after for s in plan.steps], [1])
        resized, warnings = resize_targets(
            plan, filled={}, expected=D("100"), held=D("40"), stop_steps="breakeven", ctx=ZRO
        )
        self.assertEqual([t.qty for t in resized.targets], [D("0"), D("28")])
        self.assertEqual(resized.runner, D("12"))
        self.assertEqual([s.after for s in resized.steps], [2])
        self.assertTrue(warnings)

    def test_a_position_too_small_for_any_target_rides_on_the_stop(self) -> None:
        plan = self._plan("100", "50", "20")
        resized, warnings = resize_targets(
            plan, filled={}, expected=D("100"), held=D("6"), stop_steps="breakeven", ctx=ZRO
        )
        self.assertEqual([t.qty for t in resized.targets], [D("0"), D("0")])
        self.assertEqual(resized.runner, D("6"))
        self.assertTrue(warnings)

    def test_a_larger_position_scales_the_targets_up(self) -> None:
        plan = self._plan("100", "50", "30")
        resized, _ = resize_targets(
            plan, filled={}, expected=D("100"), held=D("200"), stop_steps="breakeven", ctx=ZRO
        )
        self.assertEqual([t.qty for t in resized.targets], [D("100"), D("60")])
        self.assertEqual(resized.runner, D("40"))

    def test_each_target_shows_what_it_makes_less_the_taker_fee(self) -> None:
        plan = build_plan(_enter(), ZRO)
        # 50 × (2.40166 − 2.19082) = 10.542
        self.assertEqual(plan.targets[0].usd, D("10.54200"))
        with_fee = build_plan(_enter(), _ctx(taker_bps=D("5")))
        # less 50 × 2.40166 × 0.0005 = 0.0600415
        self.assertEqual(with_fee.targets[0].usd, D("10.4819585"))
        self.assertEqual(with_fee.targets[0].to_json()["usd"], "10.4819585")
