from __future__ import annotations

import unittest
from decimal import Decimal

from mayedge.algos.chase import (
    ALGO_ID,
    ALGO_VERSION,
    Action,
    ChaseIcebergParams,
    MarketView,
    decide,
    round_passive,
)
from mayedge.algos.chase.iceberg import leftover_is_dust

D = Decimal
TICK = D("0.01")


def mkt(
    bid: str | None,
    ask: str | None,
    *,
    min_qty: str = "1",
    tick: Decimal = TICK,
    qty_step: str = "0",
) -> MarketView:
    return MarketView(
        bid=None if bid is None else D(bid),
        ask=None if ask is None else D(ask),
        tick=tick,
        min_qty=D(min_qty),
        qty_step=D(qty_step),
    )


def buy_params(**kw: object) -> ChaseIcebergParams:
    base: dict[str, object] = dict(
        side="buy",
        qty=D("10"),
        display_qty=D("1"),
        offset_bps=D("4"),
        price_floor=D("90"),
        price_ceiling=D("100"),
    )
    base.update(kw)
    return ChaseIcebergParams(**base)  # type: ignore[arg-type]


def sell_params(**kw: object) -> ChaseIcebergParams:
    return buy_params(side="sell", **kw)


class TestChaseIcebergIdentity(unittest.TestCase):
    def test_stable_names(self) -> None:
        self.assertEqual(ALGO_ID, "chase-iceberg")
        self.assertEqual(ALGO_VERSION, "1")
        p = buy_params()
        self.assertEqual(p.offset_bps, D("4"))
        self.assertEqual(p.price_floor, D("90"))
        self.assertEqual(p.price_ceiling, D("100"))


class TestGoldenVectors(unittest.TestCase):
    def test_buy_bid_100_offset_4bps_rests_99_96(self) -> None:
        q = decide(buy_params(), mkt("100", "100.10"), remaining=D("10"))
        self.assertEqual(q.action, Action.REST)
        self.assertEqual(q.price, D("99.96"))
        self.assertEqual(q.qty, D("1"))

    def test_buy_bid_moves_to_99_99_chases_tick_rounded_passive(self) -> None:
        # 99.99 * (1 - 0.0004) = 99.950004 → ROUND_DOWN tick 0.01 → 99.95
        q = decide(buy_params(), mkt("99.99", "100.10"), remaining=D("10"))
        self.assertEqual(q.action, Action.REST)
        self.assertEqual(q.price, D("99.95"))
        self.assertEqual(q.qty, D("1"))

    def test_buy_bid_below_floor_pauses_does_not_rest_at_floor(self) -> None:
        q = decide(buy_params(), mkt("89.99", "90.10"), remaining=D("10"))
        self.assertEqual(q.action, Action.PAUSE)
        self.assertEqual(q.reason, "below_floor")
        self.assertIsNone(q.price)

    def test_buy_bid_above_ceiling_rests_at_ceiling_if_not_crossing(self) -> None:
        q = decide(buy_params(), mkt("101", "100.50"), remaining=D("10"))
        self.assertEqual(q.action, Action.REST)
        self.assertEqual(q.price, D("100"))
        self.assertEqual(q.qty, D("1"))

    def test_buy_bid_above_ceiling_pauses_if_ceiling_would_cross(self) -> None:
        q = decide(buy_params(), mkt("101", "99.99"), remaining=D("10"))
        self.assertEqual(q.action, Action.PAUSE)
        self.assertEqual(q.reason, "would_cross")

    def test_remaining_below_min_qty_pauses(self) -> None:
        """Cannot work below min qty — Pause, not a sub-min clip."""
        q = decide(buy_params(), mkt("100", "100.10"), remaining=D("0.5"))
        self.assertEqual(q.action, Action.PAUSE)
        self.assertEqual(q.reason, "below_min_qty")

    def test_leftover_is_dust(self) -> None:
        self.assertTrue(leftover_is_dust(D("0.92"), D("1")))
        self.assertFalse(leftover_is_dust(D("1"), D("1")))
        self.assertFalse(leftover_is_dust(D("0"), D("1")))
        self.assertFalse(leftover_is_dust(D("0.5"), D("0")))

    def test_last_clip_uses_remaining(self) -> None:
        q = decide(buy_params(), mkt("100", "100.10"), remaining=D("1"))
        self.assertEqual(q.action, Action.REST)
        self.assertEqual(q.qty, D("1"))
        self.assertEqual(q.price, D("99.96"))

    def test_sell_behind_ask_offset_4bps(self) -> None:
        # Twin of bid 100 → 99.96. Chase sits above the ask; band must fit 100.04.
        q = decide(
            sell_params(price_ceiling=D("110")),
            mkt("99.90", "100"),
            remaining=D("10"),
        )
        self.assertEqual(q.action, Action.REST)
        self.assertEqual(q.price, D("100.04"))
        self.assertEqual(q.qty, D("1"))

    def test_sell_ask_moves_chases_tick_rounded_passive(self) -> None:
        # 100.01 * (1 + 0.0004) = 100.050004 → ROUND_UP tick 0.01 → 100.06
        q = decide(
            sell_params(price_ceiling=D("110")),
            mkt("99.90", "100.01"),
            remaining=D("10"),
        )
        self.assertEqual(q.action, Action.REST)
        self.assertEqual(q.price, D("100.06"))

    def test_sell_ask_above_ceiling_pauses(self) -> None:
        q = decide(sell_params(), mkt("99.90", "100.01"), remaining=D("10"))
        # 100.01 is above ceiling 100
        self.assertEqual(q.action, Action.PAUSE)
        self.assertEqual(q.reason, "above_ceiling")

    def test_sell_ask_below_floor_rests_at_floor_if_not_crossing(self) -> None:
        q = decide(sell_params(), mkt("89.50", "89.00"), remaining=D("10"))
        self.assertEqual(q.action, Action.REST)
        self.assertEqual(q.price, D("90"))

    def test_sell_ask_below_floor_pauses_if_floor_would_cross(self) -> None:
        q = decide(sell_params(), mkt("90.10", "89.00"), remaining=D("10"))
        self.assertEqual(q.action, Action.PAUSE)
        self.assertEqual(q.reason, "would_cross")

    def test_would_cross_after_rounding_buy_pauses(self) -> None:
        # offset 0 joins the bid; locked book bid==ask → rest would cross
        p = buy_params(offset_bps=D("0"))
        q = decide(p, mkt("100", "100"), remaining=D("10"))
        self.assertEqual(q.action, Action.PAUSE)
        self.assertEqual(q.reason, "would_cross")

    def test_would_cross_after_rounding_sell_pauses(self) -> None:
        p = sell_params(offset_bps=D("0"))
        q = decide(p, mkt("100", "100"), remaining=D("10"))
        self.assertEqual(q.action, Action.PAUSE)
        self.assertEqual(q.reason, "would_cross")

    def test_done_when_remaining_zero(self) -> None:
        q = decide(buy_params(), mkt("100", "100.10"), remaining=D("0"))
        self.assertEqual(q.action, Action.DONE)


class TestDecideEdgeCases(unittest.TestCase):
    def test_no_book_missing_bid(self) -> None:
        q = decide(buy_params(), mkt(None, "100.10"), remaining=D("10"))
        self.assertEqual(q.action, Action.PAUSE)
        self.assertEqual(q.reason, "no_book")

    def test_no_book_zero_ask(self) -> None:
        q = decide(buy_params(), mkt("100", "0"), remaining=D("10"))
        self.assertEqual(q.action, Action.PAUSE)
        self.assertEqual(q.reason, "no_book")

    def test_invalid_band_floor_ge_ceiling(self) -> None:
        q = decide(
            buy_params(price_floor=D("100"), price_ceiling=D("100")),
            mkt("100", "100.10"),
            remaining=D("10"),
        )
        self.assertEqual(q.action, Action.PAUSE)
        self.assertEqual(q.reason, "invalid_band")

    def test_invalid_offset_negative(self) -> None:
        q = decide(buy_params(offset_bps=D("-1")), mkt("100", "100.10"), remaining=D("10"))
        self.assertEqual(q.action, Action.PAUSE)
        self.assertEqual(q.reason, "invalid_offset")

    def test_qty_step_rounds_clip_down(self) -> None:
        # display 1.25, step 0.5 → clip 1.0
        q = decide(
            buy_params(display_qty=D("1.25")),
            mkt("100", "100.10", qty_step="0.5", min_qty="0.5"),
            remaining=D("10"),
        )
        self.assertEqual(q.action, Action.REST)
        self.assertEqual(q.qty, D("1.0"))

    def test_qty_step_below_min_qty_pauses(self) -> None:
        # remaining 0.4, display 1, step 0.5 → clip 0 < min 0.5
        q = decide(
            buy_params(display_qty=D("1")),
            mkt("100", "100.10", qty_step="0.5", min_qty="0.5"),
            remaining=D("0.4"),
        )
        self.assertEqual(q.action, Action.PAUSE)
        self.assertEqual(q.reason, "below_min_qty")

    def test_round_passive_rejects_non_positive_tick(self) -> None:
        with self.assertRaises(ValueError):
            round_passive(D("100"), D("0"), "buy")

    def test_buy_offset_clamps_to_ceiling_then_rests(self) -> None:
        # bid 99.99, huge negative offset would go above ceiling without clamp path:
        # use small band where bid*(1-offset) > ceiling
        # ceiling 99.90, bid 100 → px from offset then clamp
        q = decide(
            buy_params(price_ceiling=D("99.90"), offset_bps=D("0")),
            mkt("99.95", "100.10"),
            remaining=D("10"),
        )
        self.assertEqual(q.action, Action.REST)
        self.assertEqual(q.price, D("99.90"))

    def test_sell_offset_clamps_to_floor_then_rests(self) -> None:
        # ask 90.05 with offset 0 → 90.05, floor 90.10 → clamp up to floor
        q = decide(
            sell_params(price_floor=D("90.10"), price_ceiling=D("110"), offset_bps=D("0")),
            mkt("89.00", "90.05"),
            remaining=D("10"),
        )
        self.assertEqual(q.action, Action.REST)
        self.assertEqual(q.price, D("90.10"))

    def test_done_when_remaining_negative(self) -> None:
        q = decide(buy_params(), mkt("100", "100.10"), remaining=D("-1"))
        self.assertEqual(q.action, Action.DONE)
        self.assertEqual(q.reason, "filled")


if __name__ == "__main__":
    unittest.main()
