from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import MagicMock

from mayedge.algos.ladder.config import DEFAULT_WINDOW, MAX_WINDOW
from mayedge.algos.ladder.plan import (
    LadderParams,
    build_rungs,
    filled_rung_indices,
    is_passive,
    live_rung_indices,
    select_rungs_to_place,
    validate_params,
)
from mayedge.algos.ledger import Ledger


class LadderPlanTests(unittest.TestCase):
    def test_build_buy_rungs_equal_size(self) -> None:
        rungs = build_rungs(
            side="buy",
            qty=Decimal("10"),
            price_from=Decimal("100"),
            price_to=Decimal("90"),
            rungs=5,
            tick=Decimal("0.1"),
            qty_step=Decimal("0.01"),
            min_qty=Decimal("0.1"),
        )
        self.assertEqual(len(rungs), 5)
        total = sum(r.qty for r in rungs)
        self.assertEqual(total, Decimal("10"))
        prices = [r.price for r in rungs]
        self.assertEqual(prices, sorted(prices, reverse=True))

    def test_reject_rung_below_min(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            build_rungs(
                side="buy",
                qty=Decimal("1"),
                price_from=Decimal("100"),
                price_to=Decimal("90"),
                rungs=20,
                tick=Decimal("0.1"),
                qty_step=Decimal("0.01"),
                min_qty=Decimal("0.1"),
            )
        self.assertIn("Each order must be", str(ctx.exception))

    def test_is_passive_buy(self) -> None:
        self.assertTrue(is_passive(side="buy", price=Decimal("99"), bid=Decimal("98"), ask=Decimal("100")))
        self.assertFalse(is_passive(side="buy", price=Decimal("100"), bid=Decimal("98"), ask=Decimal("100")))

    def test_window_selects_closest_unfilled(self) -> None:
        params = LadderParams(
            side="buy",
            qty=Decimal("10"),
            price_from=Decimal("100"),
            price_to=Decimal("97"),
            rungs=4,
            window=2,
        )
        params.rung_list = build_rungs(
            side="buy",
            qty=Decimal("10"),
            price_from=Decimal("100"),
            price_to=Decimal("97"),
            rungs=4,
            tick=Decimal("0.1"),
            qty_step=Decimal("0.01"),
            min_qty=Decimal("0.01"),
        )
        ledger = Ledger()
        picked = select_rungs_to_place(
            params,
            ledger=ledger,
            live_count=0,
            bid=Decimal("96"),
            ask=Decimal("101"),
        )
        self.assertEqual(len(picked), 2)
        self.assertEqual(picked[0].price, Decimal("100.0"))
        self.assertEqual(picked[1].price, Decimal("99.0"))

    def test_fill_one_refills_next_closest(self) -> None:
        params = LadderParams(
            side="buy",
            qty=Decimal("10"),
            price_from=Decimal("100"),
            price_to=Decimal("97"),
            rungs=4,
            window=2,
        )
        params.rung_list = build_rungs(
            side="buy",
            qty=Decimal("10"),
            price_from=Decimal("100"),
            price_to=Decimal("97"),
            rungs=4,
            tick=Decimal("0.1"),
            qty_step=Decimal("0.01"),
            min_qty=Decimal("0.01"),
        )
        ledger = Ledger()
        ledger.place(
            client_order_index=9_000_000_001,
            price=Decimal("100.0"),
            qty=params.rung_list[0].qty,
            now=1,
            side="buy",
        )
        ledger.clips[0].status = "filled"
        ledger.place(
            client_order_index=9_000_000_002,
            price=Decimal("99.0"),
            qty=params.rung_list[1].qty,
            now=2,
            side="buy",
        )
        live = live_rung_indices(params, ledger)
        filled = filled_rung_indices(params, ledger)
        self.assertEqual(live, {1})
        self.assertEqual(filled, {0})
        refill = select_rungs_to_place(
            params,
            ledger=ledger,
            live_count=1,
            bid=Decimal("96"),
            ask=Decimal("101"),
        )
        self.assertEqual(len(refill), 1)
        self.assertEqual(refill[0].price, Decimal("98.0"))

    def test_skips_would_cross_rungs(self) -> None:
        params = LadderParams(
            side="buy",
            qty=Decimal("4"),
            price_from=Decimal("100"),
            price_to=Decimal("97"),
            rungs=4,
            window=3,
        )
        params.rung_list = build_rungs(
            side="buy",
            qty=Decimal("4"),
            price_from=Decimal("100"),
            price_to=Decimal("97"),
            rungs=4,
            tick=Decimal("0.1"),
            qty_step=Decimal("0.01"),
            min_qty=Decimal("0.01"),
        )
        ledger = Ledger()
        picked = select_rungs_to_place(
            params,
            ledger=ledger,
            live_count=0,
            bid=Decimal("96"),
            ask=Decimal("99.5"),
        )
        self.assertTrue(all(r.price < Decimal("99.5") for r in picked))

    def test_validate_window_bounds(self) -> None:
        p = LadderParams(
            side="sell",
            qty=Decimal("5"),
            price_from=Decimal("90"),
            price_to=Decimal("100"),
            rungs=5,
            window=MAX_WINDOW + 1,
        )
        with self.assertRaises(ValueError):
            validate_params(
                p,
                tick=Decimal("0.1"),
                qty_step=Decimal("0.01"),
                min_qty=Decimal("0.01"),
            )

    def test_variance_keeps_range_and_qty(self) -> None:
        import random

        rng = random.Random(7)
        rungs = build_rungs(
            side="buy",
            qty=Decimal("10"),
            price_from=Decimal("100"),
            price_to=Decimal("90"),
            rungs=8,
            tick=Decimal("0.1"),
            qty_step=Decimal("0.01"),
            min_qty=Decimal("0.01"),
            size_var_pct=Decimal("20"),
            price_var_pct=Decimal("30"),
            rng=rng,
        )
        self.assertGreaterEqual(len(rungs), 2)
        self.assertEqual(sum(r.qty for r in rungs), Decimal("10"))
        self.assertEqual(rungs[0].price, Decimal("100.0"))
        self.assertEqual(rungs[-1].price, Decimal("90.0"))
        self.assertTrue(all(Decimal("90") <= r.price <= Decimal("100") for r in rungs))
        sizes = {r.qty for r in rungs}
        self.assertGreater(len(sizes), 1)

    def test_reject_variance_over_cap(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            build_rungs(
                side="buy",
                qty=Decimal("10"),
                price_from=Decimal("100"),
                price_to=Decimal("90"),
                rungs=5,
                tick=Decimal("0.1"),
                qty_step=Decimal("0.01"),
                min_qty=Decimal("0.01"),
                size_var_pct=Decimal("80"),
            )
        self.assertIn("Variance", str(ctx.exception))

    def test_seeded_variance_is_deterministic(self) -> None:
        from mayedge.algos.ladder.plan import NumericLcg

        a = build_rungs(
            side="buy",
            qty=Decimal("10"),
            price_from=Decimal("100"),
            price_to=Decimal("90"),
            rungs=5,
            tick=Decimal("0.1"),
            qty_step=Decimal("0.01"),
            min_qty=Decimal("0.01"),
            size_var_pct=Decimal("20"),
            price_var_pct=Decimal("10"),
            rng=NumericLcg(7),
        )
        b = build_rungs(
            side="buy",
            qty=Decimal("10"),
            price_from=Decimal("100"),
            price_to=Decimal("90"),
            rungs=5,
            tick=Decimal("0.1"),
            qty_step=Decimal("0.01"),
            min_qty=Decimal("0.01"),
            size_var_pct=Decimal("20"),
            price_var_pct=Decimal("10"),
            rng=NumericLcg(7),
        )
        self.assertEqual([(r.price, r.qty) for r in a], [(r.price, r.qty) for r in b])
        self.assertEqual(str(a[0].qty), "1.79")

    def test_low_skew_puts_more_size_at_low_prices(self) -> None:
        even = build_rungs(
            side="buy",
            qty=Decimal("10"),
            price_from=Decimal("100"),
            price_to=Decimal("90"),
            rungs=5,
            tick=Decimal("0.1"),
            qty_step=Decimal("0.01"),
            min_qty=Decimal("0.01"),
        )
        low = build_rungs(
            side="buy",
            qty=Decimal("10"),
            price_from=Decimal("100"),
            price_to=Decimal("90"),
            rungs=5,
            tick=Decimal("0.1"),
            qty_step=Decimal("0.01"),
            min_qty=Decimal("0.01"),
            size_skew=Decimal("-1"),
        )
        self.assertGreater(low[-1].qty, low[0].qty)
        self.assertGreater(low[-1].qty, even[-1].qty)
        self.assertLess(low[0].qty, even[0].qty)

    def test_high_skew_puts_more_size_at_high_prices(self) -> None:
        high = build_rungs(
            side="buy",
            qty=Decimal("10"),
            price_from=Decimal("100"),
            price_to=Decimal("90"),
            rungs=5,
            tick=Decimal("0.1"),
            qty_step=Decimal("0.01"),
            min_qty=Decimal("0.01"),
            size_skew=Decimal("1"),
        )
        self.assertGreater(high[0].qty, high[-1].qty)


class LadderStartFromBodyTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_from_body_validation(self) -> None:
        from mayedge.algos.ladder.book import LadderBook

        book = LadderBook(execution=MagicMock(), broadcast=MagicMock())
        ex = MagicMock()
        meta = MagicMock()
        meta.price_decimals = 2
        meta.size_decimals = 2
        meta.min_base_amount = Decimal("0.01")
        meta.min_quote_amount = Decimal("0")
        ex.get_market_by_index.return_value = meta
        ex.best_bid_ask.return_value = ("100", "101")
        book._execution_fn = lambda: ex

        with self.assertRaises(ValueError) as ctx:
            await book.start_from_body(
                {
                    "market_index": 1,
                    "side": "buy",
                    "qty": "0.4",
                    "price_from": "100",
                    "price_to": "90",
                    "rungs": 50,
                    "window": DEFAULT_WINDOW,
                }
            )
        self.assertIn("order", str(ctx.exception).lower())

        with self.assertRaises(ValueError):
            await book.start_from_body(
                {
                    "market_index": 1,
                    "side": "buy",
                    "qty": "10",
                    "price_from": "90",
                    "price_to": "100",
                    "rungs": 20,
                    "window": 25,
                }
            )
