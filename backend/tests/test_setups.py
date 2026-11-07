"""docs/setup-rules.md: the Setups board and its record."""

from __future__ import annotations

import asyncio
import calendar
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml

from mayedge import db as store
from mayedge.alert_settings import AlertSettings
from mayedge.config import settings
from mayedge.lighter.models import Candle, MarketMeta
from mayedge.persist_setups import KEEP_MS, record_setups, setups_listed_since
from mayedge.setups import (
    BOARD_MAX,
    MarketRead,
    Setup,
    SetupSettings,
    against_the_board,
    coiled_at_a_level,
    find_setups,
    funding_stretched,
    liquidation_flush,
    oi_without_price,
    reclaim,
    setup_settings_from_dict,
)
from mayedge.setups_board import SetupBoard, liquid, next_build_at

CFG = SetupSettings()
_DAY = 86_400
# 7 Nov 2026 12:00 UTC.
NOW = float(calendar.timegm((2026, 11, 7, 12, 0, 0)))
TODAY = int(NOW) // _DAY * _DAY


def _read(**kw: Any) -> MarketRead:
    base: dict[str, Any] = dict(market_index=1, symbol="ETH", last=100.0)
    base.update(kw)
    return MarketRead(**base)


def _days(n: int, *, low: float = 95.0, high: float = 105.0, close: float = 100.0) -> list[Candle]:
    """``n`` completed days before today, oldest first."""
    return [Candle(TODAY - (n - i) * _DAY, 100.0, high, low, close, 1.0) for i in range(n)]


class GateTest(unittest.TestCase):
    def _meta(self, **kw: Any) -> MarketMeta:
        base: dict[str, Any] = dict(
            market_index=1,
            symbol="ETH",
            price_decimals=2,
            size_decimals=4,
            min_base_amount=0.0,
            min_quote_amount=0.0,
            market_type="perp",
            volume_24h=10_000_000.0,
            last_trade_price=100.0,
            mid_price=100.0,
            best_bid_price=99.99,
            best_ask_price=100.01,
        )
        base.update(kw)
        return MarketMeta(**base)  # type: ignore[arg-type]

    def test_a_thin_market_is_not_read(self) -> None:
        thr = AlertSettings()
        self.assertTrue(liquid(self._meta(), thr))
        self.assertFalse(liquid(self._meta(volume_24h=500_000.0), thr))
        self.assertFalse(liquid(self._meta(best_bid_price=99.0, best_ask_price=101.0), thr))
        self.assertFalse(liquid(self._meta(market_type="spot"), thr))

    def test_the_board_is_rebuilt_once_an_hour(self) -> None:
        self.assertEqual(next_build_at(NOW), NOW + 3_600 + 60)
        self.assertEqual(next_build_at(NOW + 1_800), NOW + 3_600 + 60)

    def test_the_board_lists_the_largest(self) -> None:
        reads = [
            _read(market_index=i, symbol=f"M{i}", change_24h=0.0, oi_now=100.0 + i, oi_24h_ago=90.0)
            for i in range(30)
        ]
        board = find_setups(reads, None, NOW, CFG)
        self.assertEqual(len(board), BOARD_MAX)
        self.assertEqual(board[0].symbol, "M29")
        self.assertEqual([s.size for s in board], sorted((s.size for s in board), reverse=True))

    def test_the_knobs_read_from_yaml(self) -> None:
        repo = Path(__file__).resolve().parents[1] / "config" / "alerts.yaml"
        self.assertEqual(
            setup_settings_from_dict(yaml.safe_load(repo.read_text())), SetupSettings()
        )
        self.assertEqual(setup_settings_from_dict({"setups": {"oi_pct": 8}}).oi_pct, 8.0)


class SetupTest(unittest.TestCase):
    def test_open_interest_moving_without_price(self) -> None:
        found = oi_without_price(
            _read(change_24h=-0.4, oi_now=108.0, oi_24h_ago=100.0, funding_z=-3.1), CFG
        )
        assert found is not None
        self.assertEqual(found.note, "OI +8.0% 24h · price −0.4% 24h · funding −3.1σ")
        self.assertAlmostEqual(found.size, 1.6)
        # Price moved more than a third of the OI change.
        self.assertIsNone(
            oi_without_price(_read(change_24h=3.0, oi_now=108.0, oi_24h_ago=100.0), CFG)
        )
        self.assertIsNone(
            oi_without_price(_read(change_24h=0.0, oi_now=104.0, oi_24h_ago=100.0), CFG)
        )
        # No stored open interest 24h ago: not listed.
        self.assertIsNone(oi_without_price(_read(change_24h=0.0, oi_now=108.0), CFG))

    def test_funding_stretched_for_three_days(self) -> None:
        base = [0.001, -0.001] * (15 * 12)  # 15 days, median |rate| 0.001
        hot = _read(
            funding_window=[0.004] * 70 + [-0.001] * 2,
            funding_before=base,
            funding_window_complete=True,
        )
        found = funding_stretched(hot, CFG)
        assert found is not None
        self.assertEqual(found.facts["pays"], "longs")
        self.assertIn("97% one sign", found.note)
        # Mixed signs, or a missing print, or a short base: not listed.
        mixed = _read(
            funding_window=[0.004] * 60 + [-0.004] * 12,
            funding_before=base,
            funding_window_complete=True,
        )
        self.assertIsNone(funding_stretched(mixed, CFG))
        gap = _read(funding_window=[0.004] * 71, funding_before=base, funding_window_complete=False)
        self.assertIsNone(funding_stretched(gap, CFG))
        short = _read(
            funding_window=[0.004] * 72, funding_before=base[:100], funding_window_complete=True
        )
        self.assertIsNone(funding_stretched(short, CFG))

    def test_a_market_against_the_board(self) -> None:
        holds = against_the_board(_read(change_24h=3.1), -2.4, CFG)
        assert holds is not None
        self.assertEqual((holds.direction, holds.note), ("up", "+3.1% 24h · BTC −2.4%"))
        lags = against_the_board(_read(change_24h=-4.5), 1.5, CFG)
        assert lags is not None
        self.assertEqual(lags.direction, "down")
        # BTC barely moved, or the gap is small, or it is BTC.
        self.assertIsNone(against_the_board(_read(change_24h=6.0), -0.5, CFG))
        self.assertIsNone(against_the_board(_read(change_24h=1.0), -2.0, CFG))
        self.assertIsNone(against_the_board(_read(symbol="BTC", change_24h=5.0), -2.0, CFG))

    def test_a_quiet_range_under_a_week_high(self) -> None:
        wide = _days(30, low=95.0, high=105.0)
        quiet = [Candle(TODAY - (3 - i) * _DAY, 103.0, 104.0, 102.0, 103.0, 1.0) for i in range(3)]
        found = coiled_at_a_level(_read(last=103.5, daily=wide + quiet), NOW, CFG)
        assert found is not None
        self.assertEqual(found.facts["name"], "week high")
        self.assertIn("from week high 105", found.note)
        # Far from both levels.
        self.assertIsNone(coiled_at_a_level(_read(last=100.0, daily=wide + quiet), NOW, CFG))
        # Not quiet.
        self.assertIsNone(coiled_at_a_level(_read(last=104.0, daily=_days(33)), NOW, CFG))

    def test_a_failed_break_of_the_week_low(self) -> None:
        week = _days(8)[:-1]
        yesterday = Candle(TODAY - _DAY, 96.0, 99.0, 93.0, 97.0, 1.0)
        found = reclaim(_read(daily=[*week, yesterday]), NOW)
        assert found is not None
        self.assertEqual(found.direction, "up")
        self.assertEqual(found.note, "under week low 95 to 93, closed 97")
        held_under = Candle(TODAY - _DAY, 96.0, 99.0, 93.0, 94.0, 1.0)
        self.assertIsNone(reclaim(_read(daily=[*week, held_under]), NOW))
        top = Candle(TODAY - _DAY, 104.0, 107.0, 101.0, 103.0, 1.0)
        down = reclaim(_read(daily=[*week, top]), NOW)
        assert down is not None
        self.assertEqual(down.direction, "down")

    def test_a_flush_of_one_side(self) -> None:
        m = _read(oi_now=96.0e6, oi_4h_ago=100.0e6, liq_long_usd=600_000.0, liq_short_usd=10_000.0)
        found = liquidation_flush(m, CFG)
        assert found is not None
        self.assertEqual(found.note, "longs $600k liquidated in 4h · 60 bps of OI · OI −4.0%")
        # Open interest did not fall enough.
        self.assertIsNone(
            liquidation_flush(_read(oi_now=98.0e6, oi_4h_ago=100.0e6, liq_long_usd=6e5), CFG)
        )


def _setup(mi: int = 1, kind: str = "oi_price") -> Setup:
    return Setup(kind, mi, f"M{mi}", "flat", 1.5, 100.0, "note", {"oi_pct": 7.5})


class RecordTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old = settings.db_path
        store.close_db()
        settings.db_path = str(Path(self.tmp.name) / "setups.db")
        store.init_db()
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        store.close_db()
        settings.db_path = self.old

    def _rows(self) -> list[sqlite3.Row]:
        with store.reading() as conn:
            return conn.execute("SELECT * FROM setup_rows ORDER BY id").fetchall()

    def test_a_new_setup_is_written_once(self) -> None:
        listed = record_setups([_setup()], {}, now_ms=1_000)
        listed = record_setups([_setup()], listed, now_ms=2_000)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["first_at"], rows[0]["last_at"]), (1_000, 2_000))
        self.assertEqual(json.loads(rows[0]["facts"]), {"oi_pct": 7.5})
        self.assertEqual(rows[0]["price"], 100.0)

    def test_a_setup_that_comes_back_is_a_new_row(self) -> None:
        listed = record_setups([_setup()], {}, now_ms=1_000)
        listed = record_setups([], listed, now_ms=2_000)
        record_setups([_setup()], listed, now_ms=3_000)
        self.assertEqual(len(self._rows()), 2)
        # At boot, a row listed in the last two hours continues.
        self.assertEqual(setups_listed_since(2_500), {(1, "oi_price"): 2})

    def test_setup_rows_are_kept_a_year(self) -> None:
        record_setups([_setup(1)], {}, now_ms=1_000)
        record_setups([_setup(2)], {}, now_ms=1_000 + KEEP_MS + 1)
        self.assertEqual([r["symbol"] for r in self._rows()], ["M2"])

    def test_a_rebuild_reads_records_and_shows(self) -> None:
        async def read(now: float, cfg: SetupSettings) -> tuple[list[MarketRead], float | None]:
            return [_read(change_24h=3.1)], -2.4

        board = SetupBoard(CFG, read=read, clock=lambda: NOW)
        rows = asyncio.run(board.rebuild())
        self.assertEqual([s.kind for s in rows], ["board"])
        view = board.view()
        self.assertEqual(view["built_at"], int(NOW * 1000))
        self.assertEqual(view["rows"][0]["note"], "+3.1% 24h · BTC −2.4%")
        self.assertEqual(len(self._rows()), 1)


if __name__ == "__main__":
    unittest.main()
