"""Rolling baselines: the hour a spike is judged against, and the day a level is judged against."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
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


_MAD_TO_SIGMA = 1.4826
_P90_TO_SIGMA = 1.645


def robust_sigma(values: list[float], center: float, floor: float) -> float:
    """1.4826 × MAD or the 90th-percentile deviation over 1.645, whichever is larger.

    Never below ``floor``. Both are sigma on a normal series. A tape that sits still
    most minutes has a MAD of zero; the percentile still sees the moves that do print.
    """
    if not values:
        return floor
    devs = sorted(abs(v - center) for v in values)
    mad = _median(devs)
    p90 = devs[min(len(devs) - 1, int(0.9 * len(devs)))]
    return max(_MAD_TO_SIGMA * mad, p90 / _P90_TO_SIGMA, floor)


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


@dataclass
class HourBase:
    """K1: the biggest closed minute of the hour, and the minute being judged."""

    max_volume_usd: float
    max_move_pct: float
    forming_volume_usd: float


class MinuteBook:
    """Per-market 1m candles: volume multiples, and the bars an alert row is measured on."""

    def __init__(self, *, max_bars: int = 240, min_bars: int = 30) -> None:
        self._max_bars = max_bars
        self._min_bars = min_bars
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
        return MinuteMetrics(
            bar_count=len(bars),
            baseline_vol_quote=baseline,
            rvol_1m=vol_1m / baseline if baseline > 0 else 0.0,
            rvol_5m=vol_5m / expected_5m if expected_5m > 0 else 0.0,
            vol_quote_1m=vol_1m,
            vol_quote_5m=vol_5m,
        )

    def hour(self, market_index: int, *, now: float, window_min: int = 60) -> HourBase | None:
        """K1, K6. None until the book reaches a full window back."""
        dq = self._bars.get(market_index)
        if not dq:
            return None
        bars = list(dq)
        minute = int(now // 60) * 60
        start = minute - window_min * 60
        if bars[0].time > start:
            return None
        max_volume = 0.0
        max_move = 0.0
        forming = 0.0
        for i, bar in enumerate(bars):
            if bar.time < start:
                continue
            if bar.time >= minute:
                if bar.time == minute:
                    forming = self._quote_vol(bar)
                continue
            max_volume = max(max_volume, self._quote_vol(bar))
            prev = bars[i - 1] if i else None
            if prev is not None and prev.close > 0 and bar.close > 0:
                max_move = max(max_move, abs(bar.close - prev.close) / prev.close * 100.0)
        return HourBase(max_volume, max_move, forming)


class LevelBook:
    """One sample a minute for each named series of a market: premium, funding, open interest."""

    def __init__(self, *, window_min: int = 1440, min_samples: int = 30) -> None:
        self._window = window_min
        self._min_samples = min_samples
        self._series: dict[tuple[int, str], deque[tuple[int, float]]] = {}

    def samples(self, market_index: int, name: str) -> int:
        return len(self._series.get((market_index, name), ()))

    def observe(self, market_index: int, name: str, *, ts: float, value: float) -> None:
        minute = int(ts // 60)
        dq = self._series.setdefault((market_index, name), deque(maxlen=self._window))
        if dq and dq[-1][0] == minute:
            dq[-1] = (minute, value)
        elif not dq or minute > dq[-1][0]:
            dq.append((minute, value))

    def seed(self, market_index: int, name: str, samples: Iterable[tuple[int, float]]) -> None:
        """Stored minutes, from before this run. A minute already seen live keeps its live value."""
        by_minute = dict(samples)
        by_minute.update(self._series.get((market_index, name), ()))
        ordered = sorted(by_minute.items())[-self._window :]
        self._series[(market_index, name)] = deque(ordered, maxlen=self._window)

    def z(self, market_index: int, name: str, value: float, *, floor: float) -> float | None:
        """Sigmas from this series' own median. None until ``min_samples`` minutes exist."""
        series = self._series.get((market_index, name))
        if not series or len(series) < self._min_samples:
            return None
        values = [v for _minute, v in series]
        center = _median(values)
        return z_score(value, center, robust_sigma(values, center, floor))

    def changes(
        self, market_index: int, name: str, *, now: float, window_min: int
    ) -> list[float] | None:
        """K1: minute-to-minute changes over the last window, the current minute left out.

        None until the series reaches a full window back.
        """
        series = self._series.get((market_index, name))
        if not series:
            return None
        minute = int(now // 60)
        start = minute - window_min
        if series[0][0] > start:
            return None
        closed = [(m, v) for m, v in series if start - 1 <= m < minute]
        return [abs(cur[1] - prev[1]) for prev, cur in pairwise(closed)]
