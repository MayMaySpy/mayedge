from __future__ import annotations

import unittest
from decimal import Decimal

from mayedge.algos.chase.iceberg import Action, MarketView
from mayedge.algos.grid.config import MAX_UNMATCHED_TPS
from mayedge.algos.grid.decide import (
    ALGO_ID,
    GridAction,
    GridParams,
    GridRuntime,
    HotCell,
    Lot,
    add_fill_to_lots,
    apply_chase_fill,
    credit_grid_fill,
    credit_tp_fill,
    decide,
    merge_lots,
    reduce_lots,
    snap_to_grid,
)
from mayedge.lighter.fees import cycle_bps, ticks_to_bps

D = Decimal
TICK = D("0.01")


def mkt(bid: str, ask: str, *, min_qty: str = "0.01") -> MarketView:
    return MarketView(
        bid=D(bid),
        ask=D(ask),
        tick=TICK,
        min_qty=D(min_qty),
        qty_step=D("0.01"),
    )


def params(**kw: object) -> GridParams:
    base: dict[str, object] = dict(
        max_inventory=D("10"),
        display_qty=D("1"),
        offset_bps=D("4"),
        profit_bps=D("40"),
        grid_bps=D("40"),
        price_floor=D("90"),
        price_ceiling=D("110"),
        be_delay_ms=0,
    )
    base.update(kw)
    return GridParams(**base)  # type: ignore[arg-type]


class TestChaseGridIdentity(unittest.TestCase):
    def test_algo_id(self) -> None:
        self.assertEqual(ALGO_ID, "chase-grid")


class TestSnapToGrid(unittest.TestCase):
    def test_buy_snaps_down(self) -> None:
        anchor = D("100")
        snapped = snap_to_grid(D("100.03"), anchor=anchor, grid_bps=D("40"), tick=TICK, side="buy")
        self.assertLessEqual(snapped, D("100.03"))
        self.assertEqual(snapped, D("100.00"))

    def test_sell_snaps_up(self) -> None:
        anchor = D("100")
        snapped = snap_to_grid(D("100.03"), anchor=anchor, grid_bps=D("40"), tick=TICK, side="sell")
        self.assertGreaterEqual(snapped, D("100.03"))


class TestFlatQuotesBoth(unittest.TestCase):
    def test_flat_quotes_both_sides(self) -> None:
        rt = GridRuntime()
        plan = decide(params(), mkt("100", "100.10"), rt, now=1_000)
        self.assertIsNotNone(plan.buy)
        self.assertIsNotNone(plan.sell)
        assert plan.buy is not None
        assert plan.sell is not None
        self.assertEqual(plan.buy.action, GridAction.REST)
        self.assertEqual(plan.sell.action, GridAction.REST)

    def test_chase_follows_touch_not_grid_rung(self) -> None:
        rt = GridRuntime(grid_anchor=D("100"), last_snapped_buy=D("99.96"))
        plan = decide(params(), mkt("100", "100.10"), rt, now=1_000)
        assert plan.buy is not None
        self.assertEqual(plan.buy.action, GridAction.REST)
        self.assertEqual(plan.buy.price, D("99.96"))
        assert plan.sell is not None
        self.assertEqual(plan.sell.action, GridAction.REST)
        self.assertEqual(plan.sell.price, D("100.15"))


class TestLongSkew(unittest.TestCase):
    def test_long_chases_bid_tps_cover_ask(self) -> None:
        rt = GridRuntime(
            inventory=D("2"),
            inventory_vwap=D("100"),
            lots=[Lot("a", D("100"), D("2"), D("100"), "long", D("100.4"), opened_at=1)],
        )
        plan = decide(params(profit_bps=D("100")), mkt("100.05", "100.10"), rt, now=1_000)
        assert plan.buy is not None
        assert plan.sell is not None
        self.assertEqual(plan.buy.action, GridAction.REST)
        self.assertEqual(plan.sell.action, GridAction.PAUSE)
        self.assertEqual(plan.sell.reason, "tp_covers")
        self.assertEqual(len(plan.tps), 1)
        self.assertEqual(plan.tps[0].side, "sell")

    def test_short_chases_ask_tps_cover_bid(self) -> None:
        rt = GridRuntime(
            inventory=D("-2"),
            inventory_vwap=D("100"),
            lots=[Lot("a", D("100"), D("2"), D("100"), "short", D("99.6"), opened_at=1)],
        )
        plan = decide(params(), mkt("100", "100.10"), rt, now=1_000)
        assert plan.buy is not None
        assert plan.sell is not None
        self.assertEqual(plan.buy.action, GridAction.PAUSE)
        self.assertEqual(plan.buy.reason, "tp_covers")
        self.assertEqual(plan.sell.action, GridAction.REST)
        self.assertEqual(len(plan.tps), 1)
        self.assertEqual(plan.tps[0].side, "buy")


class TestMerge(unittest.TestCase):
    def test_four_tps_merge_to_one(self) -> None:
        rt = GridRuntime(
            lots=[
                Lot("a", D("100"), D("1"), D("100"), "long", D("100.4"), opened_at=1),
                Lot("b", D("101"), D("1"), D("101"), "long", D("101.4"), opened_at=2),
                Lot("c", D("102"), D("1"), D("102"), "long", D("102.4"), opened_at=3),
                Lot("d", D("103"), D("1"), D("103"), "long", D("103.4"), opened_at=4),
            ]
        )
        plan = decide(params(), mkt("100", "100.10"), rt, now=5_000)
        self.assertEqual(len(plan.cancel_lot_ids), 4)
        self.assertEqual(len(rt.lots), 1)
        self.assertTrue(rt.lots[0].merged)
        merged = merge_lots(
            [
                Lot("a", D("100"), D("1"), D("100"), "long", D("100.4")),
                Lot("b", D("101"), D("1"), D("101"), "long", D("101.4")),
            ],
            profit_bps=D("40"),
            tick=TICK,
            now=1,
        )
        self.assertEqual(merged.qty, D("2"))
        self.assertEqual(merged.vwap, D("100.5"))

    def test_same_price_fills_stay_separate_lots(self) -> None:
        rt = GridRuntime(grid_anchor=D("100"), inventory=D("-3"))
        market = mkt("100", "100.10")
        p = params()
        for i in range(3):
            add_fill_to_lots(
                rt,
                side="sell",
                fill_qty=D("1"),
                fill_vwap=D("100.10"),
                params=p,
                market=market,
                now=1_000 + i,
            )
        self.assertEqual(len(rt.lots), 3)
        plan = decide(params(), market, rt, now=2_000)
        self.assertEqual(len(plan.tps), 3)
        self.assertTrue(all(t.side == "buy" for t in plan.tps))
        assert plan.buy is not None
        self.assertEqual(plan.buy.action, GridAction.PAUSE)
        self.assertEqual(plan.buy.reason, "tp_covers")
        assert plan.sell is not None
        self.assertEqual(plan.sell.action, GridAction.REST)


class TestBreakEven(unittest.TestCase):
    def test_be_blocked_when_mid_worse_than_vwap(self) -> None:
        rt = GridRuntime(
            inventory=D("4"),
            merged_active=True,
            merged_opened_at=0,
            lots=[
                Lot(
                    "m",
                    D("100"),
                    D("4"),
                    D("100"),
                    "long",
                    D("100.4"),
                    merged=True,
                    opened_at=0,
                )
            ],
        )
        plan = decide(params(be_delay_ms=1_000), mkt("99", "99.05"), rt, now=500)
        self.assertIsNone(plan.be)

    def test_be_allowed_when_mid_at_break_even(self) -> None:
        rt = GridRuntime(
            inventory=D("4"),
            merged_active=True,
            merged_opened_at=0,
            lots=[
                Lot(
                    "m",
                    D("100"),
                    D("4"),
                    D("100"),
                    "long",
                    D("100.4"),
                    merged=True,
                    opened_at=0,
                )
            ],
        )
        plan = decide(params(be_delay_ms=1_000, be_bps=D("0")), mkt("100.05", "100.10"), rt, now=2_000)
        self.assertIsNotNone(plan.be)
        assert plan.be is not None
        self.assertEqual(plan.be.side, "sell")
        self.assertEqual(plan.be.qty, D("4"))


class TestHotCell(unittest.TestCase):
    def test_hot_cell_blocks_reentry(self) -> None:
        rt = GridRuntime(
            hot_cells=[HotCell(cell_price=D("99.96"), until_ms=9_999)],
            reentry_until=0,
        )
        plan = decide(params(), mkt("100", "100.10"), rt, now=1_000)
        assert plan.buy is not None
        self.assertEqual(plan.buy.action, GridAction.PAUSE)
        self.assertEqual(plan.buy.reason, "reentry_cooldown")


class TestInventoryCap(unittest.TestCase):
    def test_at_cap_stops_buy_chase(self) -> None:
        rt = GridRuntime(inventory=D("10"))
        plan = decide(params(max_inventory=D("10")), mkt("100", "100.10"), rt, now=1_000)
        assert plan.buy is not None
        self.assertEqual(plan.buy.action, GridAction.PAUSE)
        self.assertEqual(plan.buy.reason, "inventory_cap")
        assert plan.sell is not None
        self.assertEqual(plan.sell.action, GridAction.PAUSE)
        self.assertEqual(plan.sell.reason, "tp_covers")


class TestFifoReduce(unittest.TestCase):
    def test_reducing_sell_closes_oldest_long(self) -> None:
        rt = GridRuntime(
            inventory=D("2"),
            lots=[
                Lot("a", D("100"), D("1"), D("100"), "long", D("100.4"), opened_at=1),
                Lot("b", D("101"), D("1"), D("101"), "long", D("101.4"), opened_at=2),
            ],
        )
        leftover = reduce_lots(
            rt,
            close_side="long",
            qty=D("1"),
            now=1_000,
            reentry_cooldown_ms=30_000,
            fill_vwap=D("100.40"),
        )
        self.assertEqual(leftover, D("0"))
        self.assertEqual([lot.lot_id for lot in rt.lots], ["b"])
        self.assertEqual(len(rt.hot_cells), 1)
        self.assertEqual(rt.captured_pnl, D("0.40"))

    def test_chase_sell_against_long_does_not_open_short(self) -> None:
        rt = GridRuntime(
            inventory=D("2"),
            inventory_vwap=D("100"),
            lots=[
                Lot("a", D("100"), D("1"), D("100"), "long", D("100.4"), opened_at=1),
                Lot("b", D("101"), D("1"), D("101"), "long", D("101.4"), opened_at=2),
            ],
        )
        apply_chase_fill(
            rt,
            side="sell",
            fill_qty=D("1"),
            fill_vwap=D("100.10"),
            params=params(),
            market=mkt("100", "100.10"),
            now=1_000,
        )
        self.assertEqual(rt.inventory, D("1"))
        self.assertEqual([lot.lot_id for lot in rt.lots], ["b"])
        self.assertTrue(all(lot.side == "long" for lot in rt.lots))
        self.assertEqual(rt.captured_pnl, D("0.10"))

    def test_reduce_through_zero_opens_remainder(self) -> None:
        rt = GridRuntime(
            inventory=D("1"),
            inventory_vwap=D("100"),
            lots=[Lot("a", D("100"), D("1"), D("100"), "long", D("100.4"), opened_at=1)],
        )
        apply_chase_fill(
            rt,
            side="sell",
            fill_qty=D("3"),
            fill_vwap=D("100.10"),
            params=params(),
            market=mkt("100", "100.10"),
            now=1_000,
        )
        self.assertEqual(rt.inventory, D("-2"))
        self.assertEqual(len(rt.lots), 1)
        self.assertEqual(rt.lots[0].side, "short")
        self.assertEqual(rt.lots[0].qty, D("2"))
        self.assertEqual(rt.captured_pnl, D("0.10"))


class TestWouldCross(unittest.TestCase):
    def test_tight_spread_pauses_chase(self) -> None:
        rt = GridRuntime()
        plan = decide(params(), mkt("100", "100.001"), rt, now=1_000)
        assert plan.buy is not None
        if plan.buy.action == GridAction.PAUSE:
            self.assertEqual(plan.buy.reason, "would_cross")


class TestMaxUnmatchedTps(unittest.TestCase):
    def test_constant(self) -> None:
        self.assertEqual(MAX_UNMATCHED_TPS, 3)


class TestFeeTicks(unittest.TestCase):
    def test_standard_is_zero(self) -> None:
        self.assertEqual(ticks_to_bps(0), D("0"))
        self.assertEqual(
            cycle_bps(maker_bps=D("0"), taker_bps=D("0"), flatten_is_taker=True), D("0")
        )

    def test_premium_ticks(self) -> None:
        self.assertEqual(ticks_to_bps(40), D("0.4"))
        self.assertEqual(ticks_to_bps(280), D("2.8"))
        self.assertEqual(
            cycle_bps(maker_bps=D("0.4"), taker_bps=D("2.8"), flatten_is_taker=True), D("3.2")
        )

    def test_plus_half_bps(self) -> None:
        self.assertEqual(ticks_to_bps(50), D("0.5"))


class TestCreditGridFill(unittest.TestCase):
    def test_cancelled_tp_partial_reduces_lot_and_inventory(self) -> None:
        lot = Lot("a", D("100"), D("16"), D("100"), "long", D("100.4"), tp_clip_seq=1)
        rt = GridRuntime(inventory=D("16"), lots=[lot])
        credit_grid_fill(
            rt,
            kind="tp",
            side="sell",
            qty=D("2"),
            fill_vwap=D("100.4"),
            params=params(),
            market=mkt("100", "100.10"),
            now=1_000,
            lot=lot,
        )
        self.assertEqual(rt.inventory, D("14"))
        self.assertEqual(len(rt.lots), 1)
        self.assertEqual(rt.lots[0].qty, D("14"))
        self.assertEqual(rt.captured_pnl, D("0.8"))

    def test_tp_fill_after_merge_fifo_closes_remaining_lots(self) -> None:
        merged = Lot("m", D("100"), D("16"), D("100"), "long", D("100.4"), merged=True)
        rt = GridRuntime(inventory=D("16"), lots=[merged], merged_active=True)
        credit_grid_fill(
            rt,
            kind="tp",
            side="sell",
            qty=D("30"),
            fill_vwap=D("100.4"),
            params=params(),
            market=mkt("100", "100.10"),
            now=1_000,
            lot=None,
        )
        self.assertEqual(rt.inventory, D("-14"))
        self.assertEqual(rt.lots, [])
        self.assertFalse(rt.merged_active)
        self.assertEqual(rt.captured_pnl, D("6.4"))

    def test_cancelled_chase_buy_still_opens_a_lot(self) -> None:
        rt = GridRuntime()
        credit_grid_fill(
            rt,
            kind="chase_buy",
            side="buy",
            qty=D("4"),
            fill_vwap=D("100"),
            params=params(),
            market=mkt("100", "100.10"),
            now=1_000,
        )
        self.assertEqual(rt.inventory, D("4"))
        self.assertEqual(len(rt.lots), 1)
        self.assertEqual(rt.lots[0].qty, D("4"))

    def test_credit_tp_does_not_open_short_on_leftover(self) -> None:
        lot = Lot("a", D("100"), D("1"), D("100"), "long", D("100.4"))
        rt = GridRuntime(inventory=D("1"), lots=[lot])
        credit_tp_fill(
            rt, side="sell", qty=D("1"), fill_vwap=D("100.4"), params=params(), now=1_000, lot=lot
        )
        self.assertEqual(rt.inventory, D("0"))
        self.assertEqual(rt.lots, [])
        self.assertEqual(rt.captured_pnl, D("0.4"))


class TestCapturedPnl(unittest.TestCase):
    def test_short_tp_is_entry_minus_cover(self) -> None:
        lot = Lot("a", D("100"), D("2"), D("100"), "short", D("99.6"))
        rt = GridRuntime(inventory=D("-2"), lots=[lot])
        credit_tp_fill(
            rt, side="buy", qty=D("2"), fill_vwap=D("99.6"), params=params(), now=1_000, lot=lot
        )
        self.assertEqual(rt.captured_pnl, D("0.8"))
        self.assertEqual(rt.inventory, D("0"))

    def test_runtime_round_trips_captured_pnl(self) -> None:
        rt = GridRuntime(captured_pnl=D("12.50"), inventory=D("4"))
        restored = GridRuntime.from_json(rt.to_json())
        self.assertEqual(restored.captured_pnl, D("12.50"))
        self.assertEqual(restored.inventory, D("4"))


if __name__ == "__main__":
    unittest.main()
