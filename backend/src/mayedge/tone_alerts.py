"""Which perps closed their last bar blue or orange. Rules T1 to T5 in docs/alert-rules.md."""

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
    """Per-perp candle windows, and the blue or orange tone standing on each one's last close."""

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
        self._standing: dict[tuple[int, str], ToneHit] = {}

    def set_timeframes(self, timeframes: tuple[str, ...]) -> None:
        self.timeframes = timeframes
        keep = set(timeframes)
        for key in list(self._series):
            if key[1] not in keep:
                del self._series[key]
        for key in list(self._pending):
            if key[1] not in keep:
                del self._pending[key]
        for key in list(self._standing):
            if key[1] not in keep:
                del self._standing[key]

    def board(self) -> list[ToneHit]:
        """T1: the last closed bar of each series, where it closed blue or orange."""
        return list(self._standing.values())

    def missing(self, markets: Iterable[int]) -> list[tuple[int, str]]:
        out: list[tuple[int, str]] = []
        for market_index in markets:
            for resolution in self.timeframes:
                window = self._series.get((market_index, resolution))
                if window is None or not window.seeded:
                    out.append((market_index, resolution))
        return out

    def gaps(self, markets: Iterable[int], *, now: float) -> list[tuple[int, str]]:
        """Unseeded series, plus seeded ones whose last bar is more than one step behind."""
        out = list(self.missing(markets))
        seen = set(out)
        for market_index in markets:
            for resolution in self.timeframes:
                key = (market_index, resolution)
                if key in seen:
                    continue
                window = self._series.get(key)
                if window is None or not window.bars:
                    out.append(key)
                    continue
                step = TONE_TIMEFRAME_SECONDS[resolution]
                if now > window.bars[-1].time + 2 * step:
                    out.append(key)
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
        self._stand(market_index, resolution, window)
        pending = self._pending.pop(key, [])
        if not pending:
            return []
        return self._apply(market_index, resolution, window, pending, now=now)

    def _stand(self, market_index: int, resolution: str, window: _Window) -> None:
        """Bars loaded at boot raise nothing, but the last closed one still belongs on the board."""
        self._standing.pop((market_index, resolution), None)
        if not window.scored or len(window.bars) < self._min_bars:
            return
        last = max(window.scored)
        for i, tone in enumerate(self._tones_fn(window.bars)):
            if window.bars[i].time == last and tone in ALERT_TONES:
                self._standing[(market_index, resolution)] = ToneHit(
                    market_index, resolution, last, tone, window.bars[i].close
                )

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
        key = (market_index, resolution)
        if len(window.bars) < self._min_bars:
            window.scored.update(times)
            self._standing.pop(key, None)
            return []
        tones = self._tones_fn(window.bars)
        index = {bar.time: i for i, bar in enumerate(window.bars)}
        hits: list[ToneHit] = []
        for bar_time in sorted(times):
            window.scored.add(bar_time)
            # T5: each close replaces whatever stood before it.
            self._standing.pop(key, None)
            i = index.get(bar_time)
            if i is None or i >= len(tones):
                continue
            tone = tones[i]
            if tone not in ALERT_TONES:
                continue
            hit = ToneHit(
                market_index=market_index,
                resolution=resolution,
                bar_time=bar_time,
                tone=tone,
                close=window.bars[i].close,
            )
            self._standing[key] = hit
            hits.append(hit)
        return hits
