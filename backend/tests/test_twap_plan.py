from __future__ import annotations

from decimal import Decimal
import unittest

from mayedge.algos.twap.plan import (
    jitter,
    next_wait_s,
    order_count,
    skip_reason,
    slice_qty,
    slice_quote,
)


class TwapPlanTests(unittest.TestCase):
    def test_order_count_matches_native_formula(self) -> None:
        self.assertEqual(order_count(1800, 30), 61)
        self.assertEqual(order_count(1800, 5), 361)
        self.assertEqual(order_count(0, 5), 0)

    def test_jitter_spans_the_band(self) -> None:
        self.assertEqual(jitter(Decimal(10), Decimal("0.40"), 0.0), Decimal(6))
        self.assertEqual(jitter(Decimal(10), Decimal("0.40"), 1.0), Decimal(14))
        self.assertEqual(jitter(Decimal(10), Decimal("0.40"), 0.5), Decimal(10))

    def test_wait_without_randomize_is_exact(self) -> None:
        self.assertEqual(next_wait_s(5, False), 5.0)
        self.assertEqual(next_wait_s(5, True, 0.0), 3.0)
        self.assertEqual(next_wait_s(5, True, 1.0), 7.0)

    def test_last_slice_takes_remaining(self) -> None:
        self.assertEqual(slice_qty(Decimal("3"), 1, randomize=True, u=1.0), Decimal("3"))
        even = slice_qty(Decimal("10"), 5, randomize=False)
        self.assertEqual(even, Decimal(2))

    def test_skip_max_price_and_index(self) -> None:
        self.assertEqual(
            skip_reason(
                side="buy",
                mark=Decimal("110"),
                index=Decimal("100"),
                max_price=Decimal("105"),
                max_index_pct=None,
            ),
            "above_max_price",
        )
        self.assertEqual(
            skip_reason(
                side="buy",
                mark=Decimal("102"),
                index=Decimal("100"),
                max_price=None,
                max_index_pct=Decimal("1"),
            ),
            "past_index",
        )
        self.assertIsNone(
            skip_reason(
                side="buy",
                mark=Decimal("100.4"),
                index=Decimal("100"),
                max_price=Decimal("105"),
                max_index_pct=Decimal("1"),
            )
        )

    def test_styles_pick_market_ioc_or_post(self) -> None:
        self.assertEqual(
            slice_quote("aggressive", "buy", bid=Decimal(1), ask=Decimal(2), mid=Decimal("1.5"), mark=Decimal("1.5"))[
                "kind"
            ],
            "market",
        )
        neu = slice_quote("neutral", "buy", bid=Decimal(1), ask=Decimal(2), mid=Decimal("1.5"), mark=Decimal("1.5"))
        self.assertEqual(neu["tif"], "ioc")
        pas = slice_quote("passive", "buy", bid=Decimal(1), ask=Decimal(2), mid=Decimal("1.5"), mark=Decimal("1.5"))
        self.assertEqual(pas["tif"], "post_only")
        self.assertEqual(pas["price"], "1")


if __name__ == "__main__":
    unittest.main()
