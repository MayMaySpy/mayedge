from __future__ import annotations

import unittest

from mayedge.alert_stats import LevelBook, MinuteBook, robust_sigma, rvol_score
from mayedge.lighter.models import Candle


def _bar(i: int, close: float, vol: float) -> Candle:
    return Candle(time=1_700_000_000 + i * 60, open=close, high=close, low=close, close=close, volume=vol)


class RobustSigmaTest(unittest.TestCase):
    def test_flat_series_uses_floor(self) -> None:
        self.assertEqual(robust_sigma([0.0] * 50, 0.0, 0.05), 0.05)

    def test_noisy_series_beats_floor(self) -> None:
        values = [(-1.0) ** i for i in range(50)]
        self.assertGreater(robust_sigma(values, 0.0, 0.05), 1.0)

    def test_rvol_score_monotonic(self) -> None:
        self.assertEqual(rvol_score(1.0), 0.0)
        self.assertAlmostEqual(rvol_score(4.0), 4.0)
        self.assertLess(rvol_score(4.0), rvol_score(8.0))


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

    def test_flat_bars_floor_sigma(self) -> None:
        book = MinuteBook(min_bars=30, sigma_floor_pct=0.05)
        book.seed(1, [_bar(i, 1281.0, 1) for i in range(40)])
        m = book.metrics(1)
        assert m is not None
        self.assertEqual(m.sigma_1m_pct, 0.05)

    def test_seed_keeps_live_bars(self) -> None:
        book = MinuteBook(min_bars=2)
        book.observe(1, [_bar(50, 101, 5)])
        book.seed(1, [_bar(i, 100, 10) for i in range(40)])
        self.assertEqual(book.bar_count(1), 41)


class LevelBookTest(unittest.TestCase):
    def test_silent_until_min_samples(self) -> None:
        book = LevelBook(min_samples=30)
        for i in range(10):
            book.observe(1, ts=i * 60.0, premium=1.0, disloc_bps=10, funding=0.01, oi=1e6)
        self.assertIsNone(book.z_premium(1, 3.0, floor=0.05))

    def test_structural_level_scores_near_zero(self) -> None:
        book = LevelBook(min_samples=30)
        for i in range(40):
            book.observe(1, ts=i * 60.0, premium=1.0, disloc_bps=178, funding=0.01, oi=1e6)
        z = book.z_disloc(1, 185, floor=10)
        assert z is not None
        self.assertLess(abs(z), 1.0)

    def test_oi_change_uses_matching_lag(self) -> None:
        book = LevelBook(min_samples=30)
        oi = 1e6
        for i in range(60):
            oi *= 1.001 if i % 2 else 0.999
            book.observe(1, ts=i * 60.0, premium=0, disloc_bps=0, funding=0, oi=oi)
        z = book.z_oi_change_pct(1, 3.0, floor=0.3)
        assert z is not None
        self.assertGreater(z, 4.0)


if __name__ == "__main__":
    unittest.main()
