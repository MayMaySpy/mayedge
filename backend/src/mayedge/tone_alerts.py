"""Closed-bar blue and orange alerts for every perp."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from mayedge.lighter.models import Candle
from mayedge.mayrekt import candle_tones
from mayedge.tone_timeframes import (
    DEFAULT_TONE_TIMEFRAMES,
    TONE_TIMEFRAME_SECONDS,
)

ALERT_TONES = frozenset({"ur", "ucru"})
TONE_LABEL = {"ur": "Orange", "ucru": "Blue"}
_WINDOW = 500
_MIN_BARS = 50
_CLOSE_GRACE_S = 15.0
_PENDING_CAP = 50

TonesFn = Callable[[Sequence[Candle]], list[str | None]]


@dataclass(frozen=True)
class ToneHit:
    market_index: int
    resolution: str
    bar_time: int
    tone: str
    close: float

    @property
    def label(self) -> str:
        return TONE_LABEL[self.tone]


@dataclass
class _Window:
    bars: list[Candle]
    scored: set[int]
    seeded: bool = False


def _align(bar: Candle, step: int) -> Candle:
    opened = bar.time - (bar.time % step)
    if opened == bar.time:
        return bar
    return Candle(opened, bar.open, bar.high, bar.low, bar.close, bar.volume)


def _merge(
    existing: Sequence[Candle],
    incoming: Sequence[Candle],
    step: int,
    scored: set[int],
) -> list[Candle]:
    by_time = {bar.time: bar for bar in existing}
    for bar in incoming:
        aligned = _align(bar, step)
        if aligned.time in scored:
            continue
        by_time[aligned.time] = aligned
    ordered = sorted(by_time.values(), key=lambda bar: bar.time)
    if len(ordered) > _WINDOW:
        return ordered[-_WINDOW:]
    return ordered


def _forming_time(bars: Sequence[Candle], now: float, step: int) -> int | None:
    if not bars:
        return None
    last = bars[-1].time
    if now < last + step:
        return last
    return None


class ToneBook:
    """Per-perp candle windows. History warms the series and does not alert."""

    def __init__(
        self,
        timeframes: tuple[str, ...] = DEFAULT_TONE_TIMEFRAMES,
        tones_fn: TonesFn = candle_tones,
        *,
        min_bars: int = _MIN_BARS,
    ) -> None:
        self.timeframes = timeframes
        self._tones_fn = tones_fn
        self._min_bars = min_bars
        self._series: dict[tuple[int, str], _Window] = {}
        self._pending: dict[tuple[int, str], list[Candle]] = {}

    def set_timeframes(self, timeframes: tuple[str, ...]) -> None:
        self.timeframes = timeframes
        keep = set(timeframes)
        for key in list(self._series):
            if key[1] not in keep:
                del self._series[key]
        for key in list(self._pending):
            if key[1] not in keep:
                del self._pending[key]

    def missing(self, markets: Iterable[int]) -> list[tuple[int, str]]:
        out: list[tuple[int, str]] = []
        for market_index in markets:
            for resolution in self.timeframes:
                window = self._series.get((market_index, resolution))
                if window is None or not window.seeded:
                    out.append((market_index, resolution))
        return out

    def seed(
        self,
        market_index: int,
        resolution: str,
        bars: Sequence[Candle],
        *,
        now: float,
    ) -> list[ToneHit]:
        if resolution not in self.timeframes:
            return []
        step = TONE_TIMEFRAME_SECONDS[resolution]
        key = (market_index, resolution)
        window = _Window(bars=[], scored=set(), seeded=True)
        window.bars = _merge([], bars, step, window.scored)
        forming = _forming_time(window.bars, now, step)
        window.scored = {bar.time for bar in window.bars if bar.time != forming}
        self._series[key] = window
        pending = self._pending.pop(key, [])
        if not pending:
            return []
        return self._apply(market_index, resolution, window, pending, now=now)

    def observe(
        self,
        market_index: int,
        resolution: str,
        bars: Sequence[Candle],
        *,
        now: float,
    ) -> list[ToneHit]:
        if resolution not in self.timeframes or not bars:
            return []
        key = (market_index, resolution)
        window = self._series.get(key)
        if window is None or not window.seeded:
            bucket = self._pending.setdefault(key, [])
            bucket.extend(bars)
            if len(bucket) > _PENDING_CAP:
                del bucket[:-_PENDING_CAP]
            return []
        return self._apply(market_index, resolution, window, bars, now=now)

    def due(self, *, now: float) -> list[tuple[int, str]]:
        """Seeded series whose latest bar is past the close grace and still unscored."""
        out: list[tuple[int, str]] = []
        for (market_index, resolution), window in self._series.items():
            if self._unscored_close(window, resolution, now) is None:
                continue
            out.append((market_index, resolution))
        return out

    def close_one(self, market_index: int, resolution: str, *, now: float) -> list[ToneHit]:
        window = self._series.get((market_index, resolution))
        if window is None:
            return []
        bar_time = self._unscored_close(window, resolution, now)
        if bar_time is None:
            return []
        return self._score(market_index, resolution, window, [bar_time])

    def close_elapsed(self, *, now: float) -> list[ToneHit]:
        hits: list[ToneHit] = []
        for market_index, resolution in self.due(now=now):
            hits.extend(self.close_one(market_index, resolution, now=now))
        return hits

    def _unscored_close(self, window: _Window, resolution: str, now: float) -> int | None:
        if not window.seeded or not window.bars:
            return None
        last = window.bars[-1]
        if last.time in window.scored:
            return None
        step = TONE_TIMEFRAME_SECONDS[resolution]
        if now < last.time + step + _CLOSE_GRACE_S:
            return None
        return last.time

    def _apply(
        self,
        market_index: int,
        resolution: str,
        window: _Window,
        incoming: Sequence[Candle],
        *,
        now: float,
    ) -> list[ToneHit]:
        del now
        step = TONE_TIMEFRAME_SECONDS[resolution]
        window.bars = _merge(window.bars, incoming, step, window.scored)
        to_score = [
            bar.time
            for bar in window.bars
            if bar.time not in window.scored and any(other.time > bar.time for other in window.bars)
        ]
        if not to_score:
            return []
        return self._score(market_index, resolution, window, to_score)

    def _score(
        self,
        market_index: int,
        resolution: str,
        window: _Window,
        times: list[int],
    ) -> list[ToneHit]:
        if len(window.bars) < self._min_bars:
            window.scored.update(times)
            return []
        tones = self._tones_fn(window.bars)
        index = {bar.time: i for i, bar in enumerate(window.bars)}
        hits: list[ToneHit] = []
        for bar_time in times:
            window.scored.add(bar_time)
            i = index.get(bar_time)
            if i is None or i >= len(tones):
                continue
            tone = tones[i]
            if tone not in ALERT_TONES:
                continue
            hits.append(
                ToneHit(
                    market_index=market_index,
                    resolution=resolution,
                    bar_time=bar_time,
                    tone=tone,
                    close=window.bars[i].close,
                )
            )
        return hits
