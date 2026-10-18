"""The Tones board: which perps closed their last bar blue or orange."""

from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from mayedge.alerts import AlertDetector
from mayedge.api.app import create_app
from mayedge.lighter.gateway import LighterGateway
from mayedge.lighter.market_ws import handle_candle
from mayedge.lighter.models import Candle, MarketMeta
from mayedge.tone_alerts import ToneBook
from mayedge.tone_timeframes import (
    DEFAULT_TONE_TIMEFRAMES,
    TONE_TIMEFRAME_CAP,
    load_tone_timeframes,
    normalize_tone_timeframes,
    save_tone_timeframes,
)


def _bar(time: int, close: float = 10) -> Candle:
    return Candle(time=time, open=close, high=close + 1, low=close - 1, close=close, volume=1)


def _origin(step: int) -> int:
    raw = 1_700_000_000
    return raw - (raw % step)


def _flat(n: int, step: int = 1800, close: float = 10) -> list[Candle]:
    origin = _origin(step)
    return [_bar(origin + i * step, close) for i in range(n)]


def _tones(name: str):
    def tones(bars: Sequence[Candle]) -> list[str | None]:
        return [name] * len(bars)

    return tones


class NormalizeToneTimeframesTest(unittest.TestCase):
    def test_default_is_30m_and_4h(self) -> None:
        self.assertEqual(DEFAULT_TONE_TIMEFRAMES, ("30m", "4h"))
        self.assertEqual(TONE_TIMEFRAME_CAP, 2)

    def test_rejects_folded_and_one_second(self) -> None:
        with self.assertRaises(ValueError):
            normalize_tone_timeframes(["3m"])
        with self.assertRaises(ValueError):
            normalize_tone_timeframes(["1s"])

    def test_rejects_a_third(self) -> None:
        with self.assertRaises(ValueError):
            normalize_tone_timeframes(["30m", "4h", "1h"])

    def test_dedupes_and_allows_empty(self) -> None:
        self.assertEqual(normalize_tone_timeframes(["4h", "4h", "30m"]), ("4h", "30m"))
        self.assertEqual(normalize_tone_timeframes([]), ())

    def test_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tone_timeframes.json"
            save_tone_timeframes(("1h",), path)
            self.assertEqual(load_tone_timeframes(path), ("1h",))
            self.assertEqual(json.loads(path.read_text())["timeframes"], ["1h"])

    def test_missing_file_is_the_default(self) -> None:
        missing = Path("/tmp/mayedge-tone-timeframes-missing.json")
        missing.unlink(missing_ok=True)
        self.assertEqual(load_tone_timeframes(missing), ("30m", "4h"))


class ToneBookTest(unittest.TestCase):
    def test_seed_does_not_alert(self) -> None:
        book = ToneBook(tones_fn=_tones("ucru"), min_bars=1)
        now = _origin(1800) + 10
        hits = book.seed(1, "30m", _flat(3), now=now)
        self.assertEqual(hits, [])

    def test_forming_update_does_not_alert(self) -> None:
        book = ToneBook(tones_fn=_tones("ucru"), min_bars=1)
        start = _origin(1800)
        book.seed(1, "30m", _flat(3), now=start + 2 * 1800 + 10)
        hits = book.observe(1, "30m", [_bar(start + 2 * 1800, 11)], now=start + 2 * 1800 + 20)
        self.assertEqual(hits, [])

    def test_later_bar_closes_blue_once(self) -> None:
        book = ToneBook(tones_fn=_tones("ucru"), min_bars=1)
        start = _origin(1800)
        book.seed(7, "30m", _flat(3), now=start + 2 * 1800 + 10)
        closed = start + 2 * 1800
        nxt = closed + 1800
        hits = book.observe(7, "30m", [_bar(closed, 12), _bar(nxt, 13)], now=nxt + 5)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].tone, "ucru")
        self.assertEqual(hits[0].label, "Blue")
        self.assertEqual(hits[0].bar_time, closed)
        self.assertEqual(hits[0].market_index, 7)
        self.assertEqual(hits[0].resolution, "30m")
        again = book.observe(7, "30m", [_bar(closed, 99), _bar(nxt, 13)], now=nxt + 6)
        self.assertEqual(again, [])

    def test_orange_and_other_tones(self) -> None:
        orange = ToneBook(tones_fn=_tones("ur"), min_bars=1)
        start = _origin(14_400)
        orange.seed(1, "4h", _flat(2, step=14_400), now=start + 14_400 + 10)
        hits = orange.observe(
            1,
            "4h",
            [_bar(start + 14_400, 8), _bar(start + 2 * 14_400, 7)],
            now=start + 2 * 14_400 + 1,
        )
        self.assertEqual([hit.tone for hit in hits], ["ur"])
        self.assertEqual(hits[0].label, "Orange")

        quiet = ToneBook(tones_fn=_tones("up-strong"), min_bars=1)
        q0 = _origin(1800)
        quiet.seed(1, "30m", _flat(3), now=q0 + 2 * 1800 + 10)
        none = quiet.observe(
            1,
            "30m",
            [_bar(q0 + 2 * 1800, 10), _bar(q0 + 3 * 1800, 11)],
            now=q0 + 3 * 1800,
        )
        self.assertEqual(none, [])

    def test_clock_closes_a_quiet_bar_after_grace(self) -> None:
        book = ToneBook(tones_fn=_tones("ucru"), min_bars=1)
        start = _origin(1800)
        book.seed(1, "30m", [_bar(start)], now=start + 10)
        self.assertEqual(book.close_elapsed(now=start + 1800 + 14), [])
        hits = book.close_elapsed(now=start + 1800 + 15)
        self.assertEqual(len(hits), 1)
        self.assertEqual(book.close_elapsed(now=start + 1800 + 40), [])

    def test_short_history_does_not_alert(self) -> None:
        book = ToneBook(tones_fn=_tones("ucru"))
        start = _origin(1800)
        book.seed(1, "30m", _flat(10), now=start + 9 * 1800 + 10)
        hits = book.observe(
            1,
            "30m",
            [_bar(start + 9 * 1800), _bar(start + 10 * 1800)],
            now=start + 10 * 1800,
        )
        self.assertEqual(hits, [])

    def test_updates_before_seed_can_close_the_forming_bar(self) -> None:
        book = ToneBook(tones_fn=_tones("ur"), min_bars=1)
        start = _origin(1800)
        forming = start + 2 * 1800
        book.observe(1, "30m", [_bar(forming, 10), _bar(forming + 1800, 9)], now=forming + 1800 + 1)
        hits = book.seed(1, "30m", _flat(3), now=forming + 10)
        self.assertEqual([hit.bar_time for hit in hits], [forming])
        self.assertEqual(hits[0].tone, "ur")

    def test_dropped_timeframe_forgets_the_window(self) -> None:
        book = ToneBook(tones_fn=_tones("ucru"), min_bars=1)
        start = _origin(1800)
        book.seed(1, "30m", _flat(2), now=start + 1800 + 10)
        book.set_timeframes(("4h",))
        hits = book.observe(
            1, "30m", [_bar(start + 1800), _bar(start + 2 * 1800)], now=start + 2 * 1800
        )
        self.assertEqual(hits, [])
        self.assertEqual(book.missing([1]), [(1, "4h")])

    def test_gaps_include_unseeded_and_stale_windows(self) -> None:
        book = ToneBook(tones_fn=_tones("ucru"), min_bars=1, timeframes=("30m",))
        bars = _flat(2)
        now = bars[-1].time + 10
        self.assertEqual(book.gaps([1], now=now), [(1, "30m")])
        book.seed(1, "30m", bars, now=now)
        self.assertEqual(book.gaps([1], now=now), [])
        stale = bars[-1].time + 2 * 1800 + 1
        self.assertEqual(book.gaps([1], now=stale), [(1, "30m")])


class ToneTimeframeGatewayTest(unittest.TestCase):
    def test_set_persists_and_signals_resync(self) -> None:
        gw = LighterGateway()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tone_timeframes.json"
            with patch("mayedge.tone_timeframes.tone_timeframes_path", return_value=path):
                view = gw.set_tone_timeframes(["1h", "4h"])
            self.assertEqual(view["timeframes"], ["1h", "4h"])
            self.assertEqual(view["cap"], 2)
            self.assertEqual(load_tone_timeframes(path), ("1h", "4h"))
        self.assertTrue(gw._tone_resync.is_set())
        self.assertEqual(gw._tone_book.timeframes, ("1h", "4h"))


class ToneBoardTest(unittest.TestCase):
    def test_the_board_lists_the_last_closed_bar(self) -> None:
        # Bars loaded at boot raise nothing. The last closed one is still what the board shows.
        book = ToneBook(timeframes=("30m",), tones_fn=_tones("ucru"), min_bars=1)
        bars = _flat(4)
        self.assertEqual(book.seed(7, "30m", bars, now=bars[-1].time + 10), [])
        (hit,) = book.board()
        self.assertEqual((hit.market_index, hit.resolution, hit.label), (7, "30m", "Blue"))
        self.assertEqual(hit.bar_time, bars[-2].time)

    def test_the_next_close_clears_the_row(self) -> None:
        calls = {"tone": "ur"}

        def tones(bars: Sequence[Candle]) -> list[str | None]:
            return [calls["tone"]] * len(bars)

        book = ToneBook(timeframes=("30m",), tones_fn=tones, min_bars=1)
        bars = _flat(4)
        book.seed(7, "30m", bars, now=bars[-1].time + 10)
        self.assertEqual([hit.label for hit in book.board()], ["Orange"])
        calls["tone"] = "neutral"
        book.observe(7, "30m", [_bar(bars[-1].time + 1800)], now=bars[-1].time + 1810)
        self.assertEqual(book.board(), [])

    def test_a_dropped_timeframe_leaves_the_board(self) -> None:
        book = ToneBook(timeframes=("30m",), tones_fn=_tones("ucru"), min_bars=1)
        bars = _flat(4)
        book.seed(7, "30m", bars, now=bars[-1].time + 10)
        book.set_timeframes(("4h",))
        self.assertEqual(book.board(), [])


def _eth(volume_24h: float) -> MarketMeta:
    return MarketMeta(
        7,
        "ETH",
        2,
        4,
        0.0,
        0.0,
        market_type="perp",
        volume_24h=volume_24h,
        mark_price=10.0,
        last_trade_price=10.0,
        mid_price=10.0,
        best_bid_price=9.999,
        best_ask_price=10.001,
    )


class ToneCandleFeedTest(unittest.IsolatedAsyncioTestCase):
    async def _close_a_blue_bar(self, meta: MarketMeta) -> tuple[list[dict[str, Any]], LighterGateway]:
        sent: list[dict[str, Any]] = []
        detector = AlertDetector(sent.append)
        detector.on_market_stats(meta)
        gw = LighterGateway.__new__(LighterGateway)
        gw._current_market_index = 1
        gw._markets = {7: meta}
        gw._alerts = detector

        def on_message(message: dict[str, Any]) -> None:
            sent.append(message)

        gw.broadcast = on_message
        gw._tone_book = ToneBook(tones_fn=_tones("ucru"), min_bars=1)
        start = _origin(1800)
        gw._tone_book.seed(7, "30m", _flat(3), now=start + 2 * 1800 + 10)
        await handle_candle(
            gw,
            {
                "type": "update/candle",
                "channel": "candle/7/30m",
                "candles": [
                    {"t": start + 2 * 1800, "o": 12, "h": 13, "l": 11, "c": 12, "v": 1},
                    {"t": start + 3 * 1800, "o": 13, "h": 14, "l": 12, "c": 13, "v": 1},
                ],
            },
        )
        return sent, gw

    async def test_a_closed_bar_on_another_market_reaches_the_board_and_nothing_else(self) -> None:
        sent, gw = await self._close_a_blue_bar(_eth(10_000_000.0))
        # No chart paint, and no alert: a tone is a board row now.
        self.assertEqual(sent, [])
        self.assertEqual(gw.recent_alerts(), [])
        (row,) = gw.tone_board()
        start = _origin(1800)
        self.assertEqual((row["symbol"], row["timeframe"], row["tone"]), ("ETH", "30m", "blue"))
        self.assertEqual(row["closed_at"], (start + 3 * 1800) * 1000)

    async def test_a_thin_market_is_not_on_the_tone_board(self) -> None:
        _sent, gw = await self._close_a_blue_bar(_eth(400_000.0))
        self.assertEqual(gw.tone_board(), [])


class ToneTimeframeApiTest(unittest.IsolatedAsyncioTestCase):
    @patch("mayedge.api.app.desk.start", new_callable=AsyncMock)
    @patch("mayedge.api.app.desk.restore", new_callable=AsyncMock)
    @patch("mayedge.api.app.desk.stop", new_callable=AsyncMock)
    async def test_get_defaults_and_put_rejects_a_third(self, *_mocks: object) -> None:
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://localhost") as client:
            got = await client.get("/api/scan/tones/timeframes")
            self.assertEqual(got.status_code, 200)
            body = got.json()
            self.assertEqual(body["cap"], 2)
            self.assertIn("30m", body["choices"])
            self.assertIn("4h", body["choices"])
            self.assertLessEqual(len(body["timeframes"]), 2)
            rejected = await client.put(
                "/api/scan/tones/timeframes",
                json={"timeframes": ["30m", "4h", "1h"]},
            )
        self.assertEqual(rejected.status_code, 400)
