from __future__ import annotations

import unittest

from mayedge.alert_stats import LevelBook, MinuteBook, robust_sigma
from mayedge.lighter.models import Candle


def _bar(i: int, close: float, vol: float) -> Candle:
    return Candle(
        time=1_700_000_000 + i * 60, open=close, high=close, low=close, close=close, volume=vol
    )


class RobustSigmaTest(unittest.TestCase):
    def test_flat_series_uses_floor(self) -> None:
        self.assertEqual(robust_sigma([0.0] * 50, 0.0, 0.05), 0.05)

    def test_noisy_series_beats_floor(self) -> None:
        values = [(-1.0) ** i for i in range(50)]
        self.assertGreater(robust_sigma(values, 0.0, 0.05), 1.0)

    def test_a_tape_that_mostly_sits_still_is_not_scored_against_the_floor(self) -> None:
        # Four minutes in five print nothing, so the MAD is zero. The moves that do print are 0.2%.
        values = [0.2 if i % 10 == 0 else -0.2 if i % 10 == 5 else 0.0 for i in range(200)]
        self.assertAlmostEqual(robust_sigma(values, 0.0, 0.05), 0.2 / 1.645)

    def test_a_steady_series_keeps_its_mad(self) -> None:
        values = [(-1.0) ** i * 0.1 for i in range(50)]
        self.assertAlmostEqual(robust_sigma(values, 0.0, 0.05), 1.4826 * 0.1)


class MinuteBookTest(unittest.TestCase):
    def test_needs_min_bars(self) -> None:
        book = MinuteBook(min_bars=30)
        book.seed(1, [_bar(i, 100, 10) for i in range(10)])
        self.assertIsNone(book.metrics(1))

    def test_forming_bar_rvol(self) -> None:
        book = MinuteBook(min_bars=30)
        book.seed(1, [_bar(i, 100, 10) for i in range(40)])
        book.observe(1, [_bar(40, 100, 80)])
        m = book.metrics(1)
        assert m is not None
        self.assertAlmostEqual(m.rvol_1m, 8.0)

    def test_mean_volume_is_floored_by_the_day(self) -> None:
        book = MinuteBook(min_bars=30)
        book.seed(1, [_bar(i, 100, 0.01) for i in range(40)])
        book.observe(1, [_bar(40, 100, 500)])
        metrics = book.metrics(1, volume_floor=10_000_000 / 1440)
        assert metrics is not None
        self.assertGreater(metrics.rvol_1m, 5)
        self.assertLess(metrics.rvol_1m, 20)

    def test_seed_keeps_live_bars(self) -> None:
        book = MinuteBook(min_bars=2)
        book.observe(1, [_bar(50, 101, 5)])
        book.seed(1, [_bar(i, 100, 10) for i in range(40)])
        self.assertEqual(book.bar_count(1), 41)


class HourTest(unittest.TestCase):
    def test_the_minute_being_judged_is_not_in_its_own_hour(self) -> None:
        # Bars at 100 trading 10, then the forming minute trades 500 and jumps 3%.
        start = 1_700_000_040  # on a minute boundary, as venue bars are

        def bar(i: int, close: float, vol: float) -> Candle:
            return Candle(start + i * 60, close, close, close, close, vol)

        now = start + 70 * 60 + 20
        book = MinuteBook()
        book.seed(1, [bar(i, 100 + (i % 2) * 0.2, 10) for i in range(70)])
        book.observe(1, [bar(70, 103, 500)])
        hour = book.hour(1, now=now, window_min=60)
        assert hour is not None
        self.assertAlmostEqual(hour.max_volume_usd, 10 * 100.2)
        self.assertAlmostEqual(hour.max_move_pct, 0.2, places=2)
        self.assertAlmostEqual(hour.forming_volume_usd, 500 * 103)

        levels = LevelBook()
        minute = now // 60
        levels.seed(1, "oi", [(minute - 70 + i, 1_000.0 + (i % 2) * 5.0) for i in range(70)])
        levels.observe(1, "oi", ts=now, value=2_000.0)
        changes = levels.changes(1, "oi", now=now, window_min=60)
        assert changes is not None
        self.assertEqual(max(changes), 5.0)
        self.assertEqual(len(changes), 60)

    def test_an_hour_needs_an_hour(self) -> None:
        now = 1_700_000_000 + 40 * 60
        book = MinuteBook()
        book.seed(1, [_bar(i, 100, 10) for i in range(40)])
        self.assertIsNone(book.hour(1, now=now, window_min=60))
        levels = LevelBook()
        levels.seed(1, "oi", [(now // 60 - 30 + i, 1_000.0) for i in range(30)])
        self.assertIsNone(levels.changes(1, "oi", now=now, window_min=60))


class LevelBookTest(unittest.TestCase):
    def test_silent_until_min_samples(self) -> None:
        book = LevelBook(min_samples=30)
        for i in range(10):
            book.observe(1, "premium", ts=i * 60.0, value=1.0)
        self.assertIsNone(book.z(1, "premium", 3.0, floor=0.05))

    def test_structural_level_scores_near_zero(self) -> None:
        # A premium that has sat at 1% all day is this market's normal, not an outlier.
        book = LevelBook(min_samples=30)
        for i in range(40):
            book.observe(1, "premium", ts=i * 60.0, value=1.0)
            book.observe(1, "funding", ts=i * 60.0, value=0.01)
        near = book.z(1, "premium", 1.02, floor=0.05)
        far = book.z(1, "funding", 0.03, floor=0.002)
        assert near is not None and far is not None
        self.assertLess(abs(near), 1.0)
        self.assertGreater(far, 4.0)

    def test_a_stored_minute_does_not_replace_a_live_one(self) -> None:
        book = LevelBook(min_samples=2)
        book.observe(1, "funding", ts=600.0, value=0.02)
        book.seed(1, "funding", [(8, 0.01), (9, 0.01), (10, 0.5)])
        self.assertEqual(book.samples(1, "funding"), 3)
        # Had the stored 0.5 won, 0.5 would be this market's normal.
        self.assertGreater(book.z(1, "funding", 0.5, floor=0.002) or 0.0, 10.0)


if __name__ == "__main__":
    unittest.main()
