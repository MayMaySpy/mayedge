"""The record of alert rows: rules S1 to S5 in docs/alert-rules.md."""

from __future__ import annotations

import json
import unittest
from collections import deque
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

from mayedge import db as store
from mayedge.alert_log import (
    KNOBS,
    AlertLog,
    MemoryLogStore,
    SqliteLogStore,
    UnknownKnob,
    left_and_against,
)
from mayedge.alerts import AlertDetector, AlertSettings, MarketSnapshot
from mayedge.config import settings
from mayedge.lighter.models import Candle, MarketMeta

_ENTRY = 1_800_000_000


def _bar(t: int, high: float, low: float) -> Candle:
    return Candle(t, low, high, low, high, 1.0)


def _row(row_id: str = "alert-1-1", **kw: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": row_id,
        "ts": _ENTRY * 1000,
        "started_at": _ENTRY * 1000,
        "symbol": "ETH",
        "market_index": 1,
        "rule": "move",
        "severity": 2,
        "direction": "up",
        "price": 100.0,
        "held": "",
        "facts": [{"kind": "move", "value": 0.7, "share": 0.175}],
    }
    row.update(kw)
    return row


def _after(*bars: Candle) -> list[Candle]:
    """The bars given, then one past the horizon so the last counted bar is closed."""
    return [*bars, _bar(_ENTRY + 16 * 60, 100.0, 100.0)]


class LeftAndAgainstTest(unittest.TestCase):
    def test_left_and_against_start_at_the_alert(self) -> None:
        saved = MemoryLogStore()
        log = AlertLog(store=saved)
        log.write(_row("up"), entry_bar=_ENTRY)
        log.write(_row("down", direction="down"), entry_bar=_ENTRY)
        bars = _after(_bar(_ENTRY + 60, 101.0, 99.5), _bar(_ENTRY + 900, 100.5, 99.0))
        log.resolve(1, bars, now=_ENTRY + 1000)
        self.assertAlmostEqual(saved.rows["up"].left_pct or 0.0, 1.0)
        self.assertAlmostEqual(saved.rows["up"].against_pct or 0.0, 1.0)
        # The same bars, read the other way.
        self.assertAlmostEqual(saved.rows["down"].left_pct or 0.0, 1.0)
        self.assertAlmostEqual(saved.rows["down"].against_pct or 0.0, 1.0)
        self.assertFalse(log.awaiting(1))

    def test_the_alert_bar_is_not_counted(self) -> None:
        # The bar the row fired in ran to 105 before the alert. It is not what happened after.
        left, against = left_and_against(
            [_bar(_ENTRY, 105.0, 95.0), _bar(_ENTRY + 60, 100.4, 99.8)],
            entry_bar=_ENTRY,
            last_bar=_ENTRY + 900,
            price=100.0,
            direction="up",
        )
        self.assertAlmostEqual(left, 0.4)
        self.assertAlmostEqual(against, 0.2)

    def test_a_price_that_only_fell_left_nothing(self) -> None:
        left, against = left_and_against(
            [_bar(_ENTRY + 60, 99.5, 98.0)],
            entry_bar=_ENTRY,
            last_bar=_ENTRY + 900,
            price=100.0,
            direction="up",
        )
        self.assertEqual(left, 0.0)
        self.assertAlmostEqual(against, 2.0)

    def test_nothing_is_measured_before_the_horizon(self) -> None:
        saved = MemoryLogStore()
        log = AlertLog(store=saved)
        log.write(_row(), entry_bar=_ENTRY)
        log.resolve(1, [_bar(_ENTRY + 60, 103.0, 100.0)], now=_ENTRY + 600)
        self.assertIsNone(saved.rows["alert-1-1"].left_pct)
        self.assertTrue(log.awaiting(1))

    def test_the_market_row_is_written_and_not_measured(self) -> None:
        saved = MemoryLogStore()
        log = AlertLog(store=saved)
        log.write(_row("board", market_index=-1, rule="board", price=0.0), entry_bar=_ENTRY)
        self.assertIn("board", saved.rows)
        self.assertFalse(log.awaiting(-1))


class OpenedTest(unittest.TestCase):
    def test_opening_a_row_is_recorded_once(self) -> None:
        saved = MemoryLogStore()
        log = AlertLog(store=saved)
        log.write(_row(), entry_bar=_ENTRY)
        self.assertTrue(log.opened("alert-1-1", now_ms=5))
        self.assertTrue(log.opened("alert-1-1", now_ms=9))
        self.assertEqual(saved.rows["alert-1-1"].opened_at, 5)
        self.assertFalse(log.opened("nothing", now_ms=9))


class StatsTest(unittest.TestCase):
    def test_stats_are_per_rule(self) -> None:
        log = AlertLog(store=MemoryLogStore())
        for i, high in enumerate((101.0, 102.0, 103.0)):
            log.write(_row(f"move-{i}", market_index=i + 1), entry_bar=_ENTRY)
            log.resolve(i + 1, _after(_bar(_ENTRY + 60, high, 99.0)), now=_ENTRY + 1000)
        log.write(_row("liqs-0", market_index=9, rule="liqs"), entry_bar=_ENTRY)
        log.opened("move-0", now_ms=1)
        stats = log.stats(since_ms=0)
        self.assertEqual([row["rule"] for row in stats], ["move", "liqs"])
        self.assertEqual((stats[0]["n"], stats[0]["measured"], stats[0]["opened"]), (3, 3, 1))
        self.assertAlmostEqual(stats[0]["left"], 2.0)
        self.assertAlmostEqual(stats[0]["against"], 1.0)
        # Fired, and its bars are not in yet.
        self.assertEqual((stats[1]["n"], stats[1]["measured"], stats[1]["left"]), (1, 0, None))
        self.assertEqual(log.stats(since_ms=(_ENTRY + 1) * 1000), [])

    def test_stats_group_and_percentiles(self) -> None:
        log = AlertLog(store=MemoryLogStore())
        lefts = (1.0, 2.0, 3.0)
        againsts = (2.0, 2.0, 0.0)
        for i, (left, against) in enumerate(zip(lefts, againsts, strict=True)):
            log.write(
                _row(f"move-{i}", market_index=i + 1, symbol="ETH" if i < 2 else "BTC"),
                entry_bar=_ENTRY,
            )
            log.resolve(i + 1, _after(_bar(_ENTRY + 60, 100.0 + left, 100.0 - against)), now=_ENTRY + 1000)
        by_symbol = log.stats(since_ms=0, by="symbol")
        self.assertEqual([row["key"] for row in by_symbol], ["ETH", "BTC"])
        self.assertEqual(by_symbol[0]["n"], 2)
        move = log.stats(since_ms=0, by="rule")[0]
        self.assertAlmostEqual(move["left"], 2.0)
        self.assertAlmostEqual(move["left_p25"], 1.5)
        self.assertAlmostEqual(move["left_p75"], 2.5)
        self.assertAlmostEqual(move["left_beats"], 1 / 3)
        self.assertEqual(log.stats(since_ms=0, by="hour")[0]["key"], "08")
        with self.assertRaises(ValueError):
            log.stats(since_ms=0, by="nope")

    def test_row_retention_is_separate_from_outcomes(self) -> None:
        saved = MemoryLogStore()
        log = AlertLog(store=saved, retention_days=1, log_retention_days=90)
        log.write(_row("old"), entry_bar=_ENTRY)
        log.resolve(1, _after(), now=_ENTRY + 1000)
        late = _ENTRY + 3 * 86_400
        log.write(_row("new", ts=late * 1000, started_at=late * 1000), entry_bar=late)
        log.resolve(1, [_bar(late + 16 * 60, 100.0, 100.0)], now=late + 1000)
        self.assertEqual(sorted(saved.rows), ["new", "old"])


def _with_fact(row_id: str, kind: str, **fact: float) -> dict[str, Any]:
    return _row(row_id, rule=kind, facts=[{"kind": kind, "value": 0.0, **fact}])


class WhatIfTest(unittest.TestCase):
    def test_whatif_tightens_each_mapped_knob(self) -> None:
        for knob, (kind, field, tighter) in KNOBS.items():
            log = AlertLog(store=MemoryLogStore())
            high, low = (10.0, 1.0) if tighter == "higher" else (1.0, 10.0)
            fact_high = _fact_fields(field, high)
            fact_low = _fact_fields(field, low)
            log.write(_with_fact("keep", kind, **fact_high), entry_bar=_ENTRY)
            log.write(_with_fact("drop", kind, **fact_low), entry_bar=_ENTRY)
            current = 5.0
            tighter_value = 8.0 if tighter == "higher" else 2.0
            out = log.whatif(
                rule=kind, knob=knob, value=tighter_value, since_ms=0, current=current
            )
            self.assertFalse(out["looser"], knob)
            self.assertEqual(out["baseline"]["n"], 2, knob)
            self.assertEqual(out["whatif"]["n"], 1, knob)

    def test_a_looser_knob_returns_the_baseline(self) -> None:
        log = AlertLog(store=MemoryLogStore())
        log.write(_with_fact("a", "move", multiple=4.0), entry_bar=_ENTRY)
        out = log.whatif(rule="move", knob="spike.price_x", value=1.0, since_ms=0, current=2.0)
        self.assertTrue(out["looser"])
        self.assertEqual(out["whatif"], out["baseline"])
        self.assertEqual(out["whatif"]["n"], 1)

    def test_an_unknown_knob_is_rejected(self) -> None:
        log = AlertLog(store=MemoryLogStore())
        with self.assertRaises(UnknownKnob):
            log.whatif(rule="move", knob="rows.merge_s", value=1.0, since_ms=0, current=2.0)


def _fact_fields(field: str, number: float) -> dict[str, float]:
    if field == "multiple":
        return {"multiple": number}
    if field == "bps":
        return {"bps": number}
    if field == "abs_usd":
        return {"usd": number}
    return {"value": number}

    def test_rows_older_than_the_retention_window_are_dropped(self) -> None:
        saved = MemoryLogStore()
        log = AlertLog(store=saved, retention_days=1)
        log.write(_row("old"), entry_bar=_ENTRY)
        log.resolve(1, _after(), now=_ENTRY + 1000)
        late = _ENTRY + 3 * 86_400
        log.write(_row("new", ts=late * 1000, started_at=late * 1000), entry_bar=late)
        log.resolve(1, [_bar(late + 16 * 60, 100.0, 100.0)], now=late + 1000)
        self.assertEqual(sorted(saved.rows), ["new"])


class DetectorWritesTest(unittest.TestCase):
    def test_a_row_is_written_with_its_facts(self) -> None:
        saved = MemoryLogStore()
        det = AlertDetector(lambda message: None, AlertSettings(), log=AlertLog(store=saved))
        det._symbols[1] = "ETH"
        # An hour of flat bars, so a 0.7% minute is a spike.
        det.seed_minute_bars(
            1, [Candle(_ENTRY - (70 - i) * 60, 100.0, 100.0, 100.0, 100.0, 1.0) for i in range(70)]
        )
        det._snapshots[1] = deque([
            MarketSnapshot(
                ts=_ENTRY - 65,
                mark=100.0,
                last=100.0,
                index=100.0,
                mid=100.0,
                bid=99.99,
                ask=100.01,
                oi=5_000_000.0,
                vol_quote=10_000_000.0,
                funding=0.0,
                premium=0.0,
            )
        ])
        meta = MarketMeta(
            1,
            "ETH",
            2,
            4,
            0.0,
            0.0,
            market_type="perp",
            volume_24h=10_000_000.0,
            mark_price=100.7,
            last_trade_price=100.7,
            mid_price=100.7,
            best_bid_price=100.69,
            best_ask_price=100.71,
            open_interest=5_000_000.0,
        )
        with patch("mayedge.alerts.time.time", return_value=float(_ENTRY)):
            det.on_market_stats(meta)
        (row,) = saved.rows.values()
        self.assertEqual((row.rule, row.direction, row.price), ("move", "up", 100.7))
        self.assertAlmostEqual(json.loads(row.facts)[0]["value"], 0.7)
        # Measured from 100.7, over the bars after the one it fired in.
        det.on_minute_bars(1, _after(_bar(_ENTRY + 60, 101.707, 100.7)))
        self.assertAlmostEqual(saved.rows[row.id].left_pct or 0.0, 1.0, places=3)


class SqliteLogStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self._td = TemporaryDirectory()
        path = str(Path(self._td.name) / "mayedge.db")
        self._patch = patch.object(settings, "db_path", path)
        self._patch.start()
        store.close_db()
        store.init_db()

    def tearDown(self) -> None:
        store.close_db()
        self._patch.stop()
        self._td.cleanup()

    def test_rows_survive_a_new_store(self) -> None:
        log = AlertLog(store=SqliteLogStore())
        log.write(_row(), entry_bar=_ENTRY)
        log.write(_row(severity=3), entry_bar=_ENTRY)
        log.resolve(1, _after(_bar(_ENTRY + 60, 103.0, 99.0)), now=_ENTRY + 1000)
        self.assertTrue(log.opened("alert-1-1", now_ms=7))
        self.assertFalse(log.opened("nothing", now_ms=7))

        again = SqliteLogStore().since(0)
        self.assertEqual(len(again), 1)
        row = again[0]
        self.assertEqual((row.severity, row.opened_at, row.price), (3, 7, 100.0))
        self.assertAlmostEqual(row.left_pct or 0.0, 3.0)
        self.assertAlmostEqual(row.against_pct or 0.0, 1.0)
        self.assertEqual(AlertLog(store=SqliteLogStore()).stats(since_ms=0)[0]["n"], 1)


if __name__ == "__main__":
    unittest.main()
