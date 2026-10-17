from __future__ import annotations

import unittest
from dataclasses import replace
from decimal import Decimal as D
from typing import Any

from mayedge.algos.planner.plan import (
    MarketContext,
    PlannerParams,
    PlanRefused,
    Target,
    breakeven_price,
    build_plan,
    price_plan,
)

ZRO = MarketContext(
    tick=D("0.00001"),
    qty_step=D("1"),
    min_qty=D("5"),
    mark=D("2.19082"),
    equity=D("5537"),
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
