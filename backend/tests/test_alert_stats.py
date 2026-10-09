from __future__ import annotations

import unittest

from mayedge.alert_stats import (
    LevelBook,
    MinuteBook,
    market_beta,
    noise_sigma,
    robust_sigma,
    rvol_score,
)
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


class BroadStatsTest(unittest.TestCase):
    def test_beta_of_a_market_that_moves_with_the_board_is_one(self) -> None:
        series = {i: 1.0 if i % 2 == 0 else -1.0 for i in range(40)}
        self.assertAlmostEqual(market_beta(series, series, min_samples=30, beta_max=3), 1.0)

    def test_beta_clips_inverse_markets_to_zero_and_fast_markets_to_three(self) -> None:
        broad = {i: 1.0 if i % 2 == 0 else -1.0 for i in range(40)}
        inverse = {i: -broad[i] for i in broad}
        fast = {i: 5.0 * broad[i] for i in broad}
        self.assertEqual(market_beta(inverse, broad, min_samples=30, beta_max=3), 0.0)
        self.assertEqual(market_beta(fast, broad, min_samples=30, beta_max=3), 3.0)

    def test_recent_rms_beats_a_calm_median(self) -> None:
        calm = [0.05 if i % 2 else -0.05 for i in range(40)]
        wild = [2.0 if i % 2 else -2.0 for i in range(30)]
        sigma = noise_sigma(calm + wild + [0.01] * 5, recent_bars=30, exclude_recent=5, floor=0.05)
        self.assertGreater(sigma, 1.5)

    def test_mean_volume_is_floored_by_the_day(self) -> None:
        book = MinuteBook(min_bars=30)
        book.seed(1, [_bar(i, 100, 0.01) for i in range(40)])
        book.observe(1, [_bar(40, 100, 500)])
        metrics = book.metrics(1, volume_floor=10_000_000 / 1440)
        assert metrics is not None
        self.assertGreater(metrics.rvol_1m, 5)
        self.assertLess(metrics.rvol_1m, 20)

    def test_broad_return_is_the_median_once_enough_markets_exist(self) -> None:
        book = MinuteBook(min_bars=2)
        # Drop the last bar as forming. The remaining step is +2, +4 and +6 percent.
        for market_index, step in ((1, 102.0), (2, 104.0), (3, 106.0)):
            book.seed(
                market_index,
                [_bar(0, 100, 1), _bar(1, step, 1), _bar(2, step, 1), _bar(3, step, 1)],
            )
        series = book.broad_returns(min_markets=3)
        self.assertAlmostEqual(series[1_700_000_000 + 60], 4.0)
        self.assertEqual(book.broad_returns(min_markets=4), {})


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
