"""Rolling baselines for relative alert factors."""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise

from mayedge.lighter.models import Candle


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def robust_sigma(values: list[float], center: float, floor: float) -> float:
    """1.4826 × MAD, never below ``floor``. Flat series score against the floor, not zero."""
    if not values:
        return floor
    mad = _median([abs(v - center) for v in values])
    return max(1.4826 * mad, floor)


def z_score(value: float, center: float, sigma: float) -> float:
    if sigma <= 0:
        return 0.0
    return (value - center) / sigma


@dataclass
class MinuteMetrics:
    bar_count: int
    baseline_vol_quote: float
    rvol_1m: float
    rvol_5m: float
    vol_quote_1m: float
    vol_quote_5m: float
    sigma_1m_pct: float
    move_5m_pct: float | None = None


class MinuteBook:
    """Per-market 1m candles for volume multiples and return volatility."""

    def __init__(
        self,
        *,
        max_bars: int = 240,
        min_bars: int = 30,
        sigma_floor_pct: float = 0.05,
    ) -> None:
        self._max_bars = max_bars
        self._min_bars = min_bars
        self._sigma_floor_pct = sigma_floor_pct
        self._bars: dict[int, deque[Candle]] = {}
        self._seeded: set[int] = set()

    def seeded(self, market_index: int) -> bool:
        return market_index in self._seeded

    def bar_count(self, market_index: int) -> int:
        return len(self._bars.get(market_index, ()))

    def market_count(self) -> int:
        return len(self._bars)

    def bars(self, market_index: int) -> list[Candle]:
        return list(self._bars.get(market_index, ()))

    def seed(self, market_index: int, bars: list[Candle]) -> None:
        live = list(self._bars.get(market_index, ()))
        by_time = {bar.time: bar for bar in bars}
        for bar in live:
            by_time[bar.time] = bar
        ordered = sorted(by_time.values(), key=lambda b: b.time)
        self._bars[market_index] = deque(ordered[-self._max_bars :], maxlen=self._max_bars)
        self._seeded.add(market_index)

    def observe(self, market_index: int, bars: list[Candle]) -> None:
        if not bars:
            return
        dq = self._bars.setdefault(market_index, deque(maxlen=self._max_bars))
        for bar in sorted(bars, key=lambda b: b.time):
            if dq and dq[-1].time == bar.time:
                dq[-1] = bar
            elif not dq or bar.time > dq[-1].time:
                dq.append(bar)
            elif bar.time >= dq[0].time:
                for i, existing in enumerate(dq):
                    if existing.time == bar.time:
                        dq[i] = bar
                        break

    @staticmethod
    def _quote_vol(bar: Candle) -> float:
        return max(0.0, bar.volume) * max(bar.close, bar.open, 1e-12)

    def metrics(self, market_index: int, *, volume_floor: float = 0.0) -> MinuteMetrics | None:
        dq = self._bars.get(market_index)
        if not dq or len(dq) < self._min_bars:
            return None
        bars = list(dq)
        closed = bars[:-1]
        vols = [self._quote_vol(b) for b in closed]
        mean = sum(vols) / len(vols) if vols else 0.0
        baseline = max(mean, volume_floor, 0.0)
        vol_1m = self._quote_vol(bars[-1])
        tail5 = bars[-5:]
        vol_5m = sum(self._quote_vol(b) for b in tail5)
        expected_5m = baseline * len(tail5)

        rets = [
            (cur.close - prev.close) / prev.close * 100.0
            for prev, cur in pairwise(closed)
            if prev.close > 0 and cur.close > 0
        ]
        sigma = robust_sigma(rets, _median(rets), self._sigma_floor_pct)
        move_5m: float | None = None
        if len(bars) >= 6 and bars[-6].close > 0 and bars[-1].close > 0:
            move_5m = (bars[-1].close - bars[-6].close) / bars[-6].close * 100.0
        return MinuteMetrics(
            bar_count=len(bars),
            baseline_vol_quote=baseline,
            rvol_1m=vol_1m / baseline if baseline > 0 else 0.0,
            rvol_5m=vol_5m / expected_5m if expected_5m > 0 else 0.0,
            vol_quote_1m=vol_1m,
            vol_quote_5m=vol_5m,
            sigma_1m_pct=sigma,
            move_5m_pct=move_5m,
        )

    def closed_return_map(self, market_index: int) -> dict[int, float]:
        """Close-to-close percent returns of closed bars, keyed by bar open time.

        The newest bar is treated as still forming and dropped.
        """
        bars = self.bars(market_index)
        if len(bars) < 3:
            return {}
        out: dict[int, float] = {}
        for prev, cur in pairwise(bars[:-1]):
            if prev.close <= 0 or cur.close <= 0:
                continue
            out[cur.time] = (cur.close - prev.close) / prev.close * 100.0
        return out

    def broad_returns(self, *, min_markets: int) -> dict[int, float]:
        """Median 1m return across markets, for minutes with enough names."""
        bucket: dict[int, list[float]] = {}
        for market_index in self._bars:
            for minute, ret in self.closed_return_map(market_index).items():
                bucket.setdefault(minute, []).append(ret)
        return {
            minute: _median(vals) for minute, vals in bucket.items() if len(vals) >= min_markets
        }


@dataclass
class LevelSample:
    ts_min: int
    premium: float
    disloc_bps: float | None
    funding: float
    oi: float


class LevelBook:
    """One sample per minute. Level factors stay silent until ``min_samples`` minutes exist."""

    def __init__(self, *, window_min: int = 1440, min_samples: int = 30) -> None:
        self._window = window_min
        self._min_samples = min_samples
        self._samples: dict[int, deque[LevelSample]] = {}

    def samples(self, market_index: int) -> int:
        return len(self._samples.get(market_index, ()))

    def observe(
        self,
        market_index: int,
        *,
        ts: float,
        premium: float,
        disloc_bps: float | None,
        funding: float,
        oi: float,
    ) -> None:
        minute = int(ts // 60)
        sample = LevelSample(minute, premium, disloc_bps, funding, oi)
        dq = self._samples.setdefault(market_index, deque(maxlen=self._window))
        if dq and dq[-1].ts_min == minute:
            dq[-1] = sample
        else:
            dq.append(sample)

    def z_premium(self, market_index: int, premium: float, *, floor: float) -> float | None:
        return self._z(market_index, premium, lambda s: s.premium, floor)

    def z_disloc(self, market_index: int, disloc_bps: float, *, floor: float) -> float | None:
        return self._z(market_index, disloc_bps, lambda s: s.disloc_bps, floor)

    def z_funding(self, market_index: int, funding: float, *, floor: float) -> float | None:
        return self._z(market_index, funding, lambda s: s.funding, floor)

    def z_oi_change_pct(
        self, market_index: int, oi_change_pct: float, *, lag: int = 5, floor: float
    ) -> float | None:
        """Score a ``lag``-minute OI change against this market's own ``lag``-minute changes."""
        series = list(self._samples.get(market_index, ()))
        if len(series) < self._min_samples:
            return None
        changes = [
            (cur.oi - prev.oi) / prev.oi * 100.0
            for prev, cur in zip(series, series[lag:], strict=False)
            if prev.oi > 0 and cur.oi > 0
        ]
        if len(changes) < self._min_samples // 2:
            return None
        center = _median(changes)
        return z_score(oi_change_pct, center, robust_sigma(changes, center, floor))

    def _z(
        self,
        market_index: int,
        value: float,
        pick: Callable[[LevelSample], float | None],
        floor: float,
    ) -> float | None:
        series = self._samples.get(market_index)
        if not series or len(series) < self._min_samples:
            return None
        values = [v for v in (pick(s) for s in series) if v is not None]
        if len(values) < self._min_samples:
            return None
        center = _median(values)
        return z_score(value, center, robust_sigma(values, center, floor))


def rvol_score(rvol: float) -> float:
    if rvol <= 1.0:
        return 0.0
    return 2.0 * math.log2(rvol)


def market_beta(
    market: dict[int, float],
    broad: dict[int, float],
    *,
    min_samples: int,
    beta_max: float,
) -> float:
    """``cov / var`` of aligned 1m returns, clipped to ``[0, beta_max]``.

    Too few overlapping minutes, or a flat Broad series, scores as 0: the
    market is treated as moving on its own.
    """
    xs: list[float] = []
    ys: list[float] = []
    for minute, y in market.items():
        x = broad.get(minute)
        if x is None:
            continue
        xs.append(x)
        ys.append(y)
    if len(xs) < min_samples:
        return 0.0
    mean_x = sum(xs) / len(xs)
    var = sum((x - mean_x) ** 2 for x in xs)
    if var <= 1e-18:
        return 0.0
    mean_y = sum(ys) / len(ys)
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    return min(beta_max, max(0.0, cov / var))


def noise_sigma(
    values: list[float],
    *,
    recent_bars: int,
    exclude_recent: int,
    floor: float,
) -> float:
    """The larger of the full-window robust sigma and the recent RMS.

    The newest ``exclude_recent`` points are left out of the RMS so the move
    being scored does not widen its own baseline.
    """
    if len(values) < 5:
        return floor
    robust = robust_sigma(values, _median(values), floor)
    if len(values) <= exclude_recent + 5:
        return robust
    window = values[: len(values) - exclude_recent][-recent_bars:]
    if len(window) < 5:
        return robust
    rms = math.sqrt(sum(v * v for v in window) / len(window))
    return max(robust, rms)
