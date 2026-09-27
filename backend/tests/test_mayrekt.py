"""MayRekt tones match the chart cases."""

from __future__ import annotations

import unittest

from mayedge.lighter.models import Candle
from mayedge.mayrekt import candle_tones

_UP = ("up-strong", "up-weak")
_DOWN = ("down-strong", "down-weak")


def _bar(time: int, **partial: float) -> Candle:
    return Candle(
        time=time,
        open=partial.get("open", 10),
        high=partial.get("high", 11),
        low=partial.get("low", 9),
        close=partial.get("close", 10),
        volume=partial.get("volume", 1),
    )


def _series(n: int, at) -> list[Candle]:
    bars: list[Candle] = []
    for i in range(n):
        fields = {"volume": 10.0, **at(i)}
        bars.append(_bar(1_700_000_000 + i * 60, **fields))
    return bars


class CandleTonesTest(unittest.TestCase):
    def test_single_bar_is_untoned(self) -> None:
        self.assertEqual(candle_tones([_bar(60)]), [None])

    def test_flat_series_ends_neutral(self) -> None:
        tones = candle_tones(
            _series(200, lambda _i: {"open": 100, "high": 101, "low": 99, "close": 100})
        )
        self.assertEqual(len(tones), 200)
        self.assertEqual(tones[199], "neutral")

    def test_rising_series_ends_up(self) -> None:
        def at(i: int) -> dict[str, float]:
            low = 100 + i
            return {"open": low, "high": low + 1, "low": low, "close": low + 1}

        last = candle_tones(_series(200, at))[199]
        self.assertIn(last, _UP)
        self.assertNotEqual(last, "neutral")
        self.assertFalse(last in _DOWN or str(last).startswith("breakdown"))

    def test_falling_series_ends_down(self) -> None:
        def at(i: int) -> dict[str, float]:
            high = 400 - i
            return {"open": high, "high": high, "low": high - 1, "close": high - 1}

        last = candle_tones(_series(200, at))[199]
        self.assertIn(last, _DOWN)
        self.assertNotEqual(last, "neutral")
        self.assertFalse(last in _UP or str(last).startswith("breakout"))

    def test_breakout_beats_up(self) -> None:
        flat = _series(120, lambda _i: {"open": 100, "high": 101, "low": 99, "close": 100})
        start = flat[-1].time
        dip = [
            _bar(
                start + (step + 1) * 60,
                open=close + 2,
                high=close + 2,
                low=close,
                close=close,
                volume=10,
            )
            for step, close in enumerate((98, 96, 94))
        ]
        spike = _bar(start + 4 * 60, open=94, high=110, low=94, close=108, volume=10)
        tones = candle_tones([*flat, *dip, spike])
        self.assertEqual(tones[119], "neutral")
        self.assertIn(tones[-1], ("breakout-strong", "breakout-weak"))
