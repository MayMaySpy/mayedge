"""journal-rules, Excursion: MAE and MFE from the average entry, over the bars of the trip."""

from __future__ import annotations

import unittest
from decimal import Decimal

from mayedge.journal_excursion import excursion, resolution_for
from mayedge.lighter.models import Candle


def _bar(t: int, high: float, low: float) -> Candle:
    return Candle(time=t, open=low, high=high, low=low, close=high, volume=1)


class ResolutionTests(unittest.TestCase):
    def test_the_smallest_bar_that_fits_one_read(self) -> None:
        self.assertEqual(resolution_for(0, 3600), ("1m", 60, 62))
        self.assertEqual(resolution_for(0, 86_400)[0], "5m")
        self.assertEqual(resolution_for(0, 30 * 86_400)[0], "4h")
        self.assertEqual(resolution_for(0, 5 * 365 * 86_400), ("1d", 86_400, 500))


_BARS = [_bar(0, 99, 95), _bar(60, 104, 97), _bar(120, 120, 80), _bar(180, 200, 50)]


class ExcursionTests(unittest.TestCase):
    def test_a_long_measures_down_against_and_up_for(self) -> None:
        # Bars at 0 and 60 cover a trip open from 30 to 100; the bar at 120 starts after it closed.
        found = excursion("long", Decimal(100), Decimal(2), _BARS, 30, 100, "1m", 60)
        assert found is not None
        self.assertEqual(found.mae_pct, Decimal(-5))
        self.assertEqual(found.mfe_pct, Decimal(4))
        self.assertEqual(found.mae_usd, Decimal(-10))
        self.assertEqual(found.mfe_usd, Decimal(8))

    def test_a_short_measures_up_against_and_down_for(self) -> None:
        found = excursion("short", Decimal(100), Decimal(-2), _BARS, 30, 100, "1m", 60)
        assert found is not None
        self.assertEqual(found.mae_pct, Decimal(-4))
        self.assertEqual(found.mfe_pct, Decimal(5))
        self.assertEqual(found.mfe_usd, Decimal(10))

    def test_a_move_that_never_went_against_is_zero_not_a_gain(self) -> None:
        found = excursion("long", Decimal(90), Decimal(1), [_bar(0, 99, 95)], 0, 30, "1m", 60)
        assert found is not None
        self.assertEqual(found.mae_pct, Decimal(0))

    def test_no_bar_or_no_entry_is_unknown(self) -> None:
        self.assertIsNone(excursion("long", Decimal(100), Decimal(1), [], 0, 60, "1m", 60))
        self.assertIsNone(excursion("long", Decimal(0), Decimal(1), _BARS, 0, 60, "1m", 60))


if __name__ == "__main__":
    unittest.main()
