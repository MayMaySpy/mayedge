"""Rolling baselines: the Usual move a span is judged against, and the days a level is judged against."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass

from mayedge.lighter.models import Candle

_DAY_S = 86_400


def completed_extremes(
    bars: Iterable[Candle], *, now: float, days: int
) -> tuple[float, float] | None:
    """W1. High and low of the completed UTC days before today. Today is not in it."""
    if days <= 0:
        return None
    today = int(now) // _DAY_S * _DAY_S
    start = today - days * _DAY_S
    chosen = [bar for bar in bars if start <= bar.time < today and bar.high > 0 and bar.low > 0]
    if len(chosen) < days:
        return None
    return max(bar.high for bar in chosen), min(bar.low for bar in chosen)


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
class SpanBase:
    """M1, M2, M6: one span of a market's tape, judged against its own last 240 closed bars."""

    span: int
    ref_close: float
    usual_pct: float
    volume_usd: float
    mean_volume_usd: float


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

    def _closed(self, market_index: int, now: float) -> list[Candle]:
        minute = int(now // 60) * 60
        return [bar for bar in self._bars.get(market_index, ()) if bar.time < minute]

    def live_share(self, market_index: int, *, now: float, bars: int) -> float | None:
        """G4: the share of the last ``bars`` closed minutes that traded. None until there are that many."""
        closed = self._closed(market_index, now)[-bars:]
        if len(closed) < bars:
            return None
        return sum(1 for bar in closed if bar.volume > 0) / bars

    def ref_close(self, market_index: int, span: int, *, now: float) -> float | None:
        """M1, M4: the close ``span`` closed bars back."""
        closed = self._closed(market_index, now)
        if len(closed) < span or span < 1:
            return None
        close = closed[-span].close
        return close if close > 0 else None

    def span(self, market_index: int, span: int, *, now: float, bars: int) -> SpanBase | None:
        """M1, M2, M6. None until ``bars`` closed minutes are behind it."""
        closed = self._closed(market_index, now)
        if len(closed) < bars or span < 1:
            return None
        window = closed[-bars:]
        closes = [bar.close for bar in window]
        moves = [
            abs(closes[i] - closes[i - span]) / closes[i - span] * 100.0
            for i in range(span, len(closes))
            if closes[i - span] > 0 and closes[i] > 0
        ]
        ref = closes[-span]
        if not moves or ref <= 0:
            return None
        minute = int(now // 60) * 60
        forming = [bar for bar in self._bars.get(market_index, ()) if bar.time >= minute]
        recent = window[-(span - 1) :] if span > 1 else []
        volume = sum(self._quote_vol(bar) for bar in [*recent, *forming])
        mean = sum(self._quote_vol(bar) for bar in window) / len(window) * span
        return SpanBase(span, ref, _median(moves), volume, mean)


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

    def back(self, market_index: int, name: str, *, now: float, minutes: int) -> float | None:
        """M6: the sample ``minutes`` before this minute. None when that minute is a gap."""
        want = int(now // 60) - minutes
        for minute, value in reversed(self._series.get((market_index, name), ())):
            if minute == want:
                return value
            if minute < want:
                return None
        return None
