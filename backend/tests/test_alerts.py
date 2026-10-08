from __future__ import annotations

import unittest
from collections import deque
from pathlib import Path
from typing import Any
from unittest.mock import patch

from mayedge.alerts import (
    AlertSettings,
    EpisodeBook,
    ExploitDetector,
    Factor,
    MarketSnapshot,
    SevPair,
    composite_score,
    load_thresholds,
    thresholds_from_dict,
)
from mayedge.lighter.gateway import LighterGateway
from mayedge.lighter.models import Candle, MarketMeta, open_interest_usd

_T0 = 1_800_000_000.0
_BAR0 = int(_T0) - 40 * 60

_TEST_THR = AlertSettings(
    min_severity=2,
    max_events_per_flush=50,
    warmup_s=0.0,
    min_bars=30,
    level_min_samples=30,
    min_24h_usd=1_000_000.0,
    vol_min_usd_1m=1_000.0,
    max_new_per_min=50,
)


def _meta(**kwargs: object) -> MarketMeta:
    base: dict[str, object] = dict(
        market_index=1,
        symbol="ETH",
        price_decimals=2,
        size_decimals=4,
        min_base_amount=0.0,
        min_quote_amount=0.0,
        market_type="perp",
        volume_24h=10_000_000.0,
        mark_price=100.0,
        last_trade_price=100.0,
        mid_price=100.0,
        best_bid_price=99.99,
        best_ask_price=100.01,
        open_interest=5_000_000.0,
    )
    base.update(kwargs)
    return MarketMeta(**base)  # type: ignore[arg-type]


def _bars(closes: list[float], vol: float = 1_000.0) -> list[Candle]:
    return [
        Candle(time=_BAR0 + i * 60, open=c, high=c, low=c, close=c, volume=vol)
        for i, c in enumerate(closes)
    ]


def _wiggle(n: int, step_pct: float) -> list[float]:
    out = [100.0]
    for i in range(1, n):
        out.append(out[-1] * (1 + (step_pct if i % 2 else -step_pct) / 100.0))
    return out


def _snap(ts: float, **kw: float) -> MarketSnapshot:
    row: dict[str, float] = dict(
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
    row.update(kw)
    return MarketSnapshot(ts=ts, **row)


class Harness:
    def __init__(self, thr: AlertSettings = _TEST_THR) -> None:
        self.messages: list[dict[str, Any]] = []
        self.det = ExploitDetector(self.messages.append, thresholds=thr)

    def seed_snapshots(self, mi: int, snaps: list[MarketSnapshot]) -> None:
        self.det._snapshots[mi] = deque(snaps, maxlen=400)
        self.det._seen_since[mi] = snaps[0].ts

    def seed_levels(self, mi: int, minutes: int, **kw: float) -> None:
        for i in range(minutes):
            s = _snap(_T0 - (minutes - i) * 60, **kw)
            disloc = abs(s.mark - s.mid) / s.mid * 10_000
            self.det._level.observe(
                mi, ts=s.ts, premium=s.premium, disloc_bps=disloc, funding=s.funding, oi=s.oi
            )

    def tick(self, meta: MarketMeta, at: float = _T0) -> list[dict[str, Any]]:
        before = len(self.messages)
        with patch("mayedge.alerts.time.time", return_value=at):
            self.det.on_market_stats(meta)
            self.det.flush()
        return [e for m in self.messages[before:] for e in m.get("events", [])]


class ApplyMarketStatsTest(unittest.TestCase):
    def test_apply_market_stats_parses_extended_fields(self) -> None:
        gw = LighterGateway()
        gw._markets[1] = _meta()
        gw._apply_market_stats(
            {
                "market_stats": {
                    "market_id": 1,
                    "mark_price": "2000",
                    "open_interest": "5000000",
                    "best_bid_price": "1998",
                    "mid_price": "2000",
                }
            }
        )
        meta = gw._markets[1]
        self.assertEqual(meta.open_interest, 10_000_000.0)
        self.assertEqual(meta.best_bid_price, 1998.0)
        self.assertEqual(meta.mark_price, 2000.0)

    def test_open_interest_usd_matches_official_two_sided(self) -> None:
        self.assertEqual(open_interest_usd(54_100_000), 108_200_000)


class ThresholdYamlTest(unittest.TestCase):
    def test_nested_price_block(self) -> None:
        thr = thresholds_from_dict({"factors": {"price": {"sigma": [5, 9], "min_pct": [0.4, 0.8]}}})
        self.assertEqual(thr.price_sigma, SevPair(5.0, 9.0))
        self.assertEqual(thr.price_min_pct_1m, 0.4)
        self.assertEqual(thr.price_min_pct_5m, 0.8)

    def test_load_repo_yaml(self) -> None:
        thr = load_thresholds(Path(__file__).resolve().parents[1] / "config" / "alerts.yaml")
        self.assertEqual(thr.score_sev2, 4.0)
        self.assertGreater(thr.disloc_sigma_floor_bps, 0)
        self.assertGreaterEqual(thr.min_24h_usd, 1_000_000)


class PriceFactorTest(unittest.TestCase):
    def test_tick_on_flat_book_is_not_an_outlier(self) -> None:
        h = Harness()
        h.det.seed_minute_bars(1, _bars([1281.0] * 40))
        h.seed_snapshots(1, [_snap(_T0 - 65, last=1281.0, mark=1281.0)])
        events = h.tick(_meta(last_trade_price=1282.15, mark_price=1282.15))
        self.assertEqual(events, [])

    def test_same_move_fires_on_quiet_market_only(self) -> None:
        quiet = Harness()
        quiet.det.seed_minute_bars(1, _bars(_wiggle(40, 0.1)))
        quiet.seed_snapshots(1, [_snap(_T0 - 65)])
        fired = quiet.tick(_meta(last_trade_price=101.5, mark_price=101.5))
        self.assertEqual([e["kind"] for e in fired], ["signal"])
        self.assertEqual(fired[0]["setup"], "pump")
        self.assertEqual(fired[0]["direction"], "up")

        wild = Harness()
        wild.det.seed_minute_bars(1, _bars(_wiggle(40, 1.0)))
        wild.seed_snapshots(1, [_snap(_T0 - 65)])
        self.assertEqual(wild.tick(_meta(last_trade_price=101.5, mark_price=101.5)), [])


class VolumeFactorTest(unittest.TestCase):
    def test_normal_volume_on_big_market_is_quiet(self) -> None:
        h = Harness()
        h.det.seed_minute_bars(1, _bars([100.0] * 40, vol=20_000.0))
        h.seed_snapshots(1, [_snap(_T0 - 65)])
        self.assertEqual(h.tick(_meta()), [])

    def test_volume_burst_with_flat_price_is_absorption(self) -> None:
        h = Harness()
        bars = _bars(_wiggle(40, 0.1))
        bars[-1].volume = 10_000.0
        h.det.seed_minute_bars(1, bars)
        h.seed_snapshots(1, [_snap(_T0 - 305), _snap(_T0 - 65)])
        events = h.tick(_meta())
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["setup"], "absorption")

    def test_volume_burst_during_rally_is_a_surge_not_absorption(self) -> None:
        h = Harness()
        bars = _bars(_wiggle(40, 0.1))
        bars[-1].volume = 10_000.0
        h.det.seed_minute_bars(1, bars)
        h.seed_snapshots(1, [_snap(_T0 - 305), _snap(_T0 - 65, last=100.4, mark=100.4)])
        events = h.tick(_meta(last_trade_price=100.5, mark_price=100.5))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["setup"], "vol_surge")
        self.assertEqual(events[0]["direction"], "up")

    def test_right_after_restart_candles_give_the_price_context(self) -> None:
        flat = Harness()
        bars = _bars(_wiggle(40, 0.1))
        bars[-1].volume = 10_000.0
        flat.det.seed_minute_bars(1, bars)
        flat.seed_snapshots(1, [_snap(_T0 - 65)])
        events = flat.tick(_meta())
        self.assertEqual([e["setup"] for e in events], ["absorption"])
        self.assertIsNotNone(flat.det.board()[0]["move_pct"])

        rally = Harness()
        bars = _bars([*_wiggle(35, 0.1), 100.3, 100.6, 100.9, 101.2, 101.5])
        bars[-1].volume = 10_000.0
        rally.det.seed_minute_bars(1, bars)
        rally.seed_snapshots(1, [_snap(_T0 - 65, last=101.5, mark=101.5)])
        events = rally.tick(_meta(last_trade_price=101.5, mark_price=101.5))
        self.assertEqual([(e["setup"], e["direction"]) for e in events], [("vol_surge", "up")])
        self.assertGreater(rally.det.board()[0]["move_pct"], 1.0)


class LevelFactorTest(unittest.TestCase):
    def _disloc_meta(self, mark: float) -> MarketMeta:
        return _meta(mark_price=mark, last_trade_price=100.0)

    def test_no_level_alert_without_history(self) -> None:
        h = Harness()
        h.seed_snapshots(1, [_snap(_T0 - 65)])
        self.assertEqual(h.tick(self._disloc_meta(101.78)), [])

    def test_structural_dislocation_is_quiet(self) -> None:
        h = Harness()
        h.seed_levels(1, 60, mark=101.78)
        h.seed_snapshots(1, [_snap(_T0 - 65, mark=101.78)])
        self.assertEqual(h.tick(self._disloc_meta(101.85)), [])

    def test_new_dislocation_on_tight_market_fires(self) -> None:
        h = Harness()
        h.seed_levels(1, 60)
        h.seed_snapshots(1, [_snap(_T0 - 65)])
        events = h.tick(self._disloc_meta(100.8))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["setup"], "mark_off_book")
        self.assertEqual(events[0]["factors"][0]["kind"], "dislocation")


class GateTest(unittest.TestCase):
    def test_thin_market_never_alerts_or_boards(self) -> None:
        h = Harness()
        h.det.seed_minute_bars(1, _bars(_wiggle(40, 0.1)))
        h.seed_snapshots(1, [_snap(_T0 - 65, vol_quote=600_000.0)])
        events = h.tick(_meta(last_trade_price=101.5, mark_price=101.5, volume_24h=600_000.0))
        self.assertEqual(events, [])
        self.assertEqual(h.det._episodes.board_rows(_T0), [])


class EpisodeBookTest(unittest.TestCase):
    def test_composite_score_weights(self) -> None:
        s = composite_score(
            [Factor("price", "up", 1.0, "pct", 6.0), Factor("volume", "up", 4.0, "x", 4.0)]
        )
        self.assertAlmostEqual(s, 8.0)

    def test_factors_merge_into_one_row_with_stable_id(self) -> None:
        book = EpisodeBook(_TEST_THR)
        ev1 = book.ingest(1, "ETH", [Factor("price", "down", -2.0, "pct", 5.0, "1m")], _T0, liquidity_ok=True)
        ev2 = book.ingest(1, "ETH", [Factor("volume", "up", 6.0, "x", 5.0, "1m")], _T0 + 1, liquidity_ok=True)
        assert ev1 is not None and ev2 is not None
        self.assertEqual(ev1.id, ev2.id)
        self.assertEqual({f["kind"] for f in ev2.factors or []}, {"price", "volume"})

    def test_unchanged_episode_does_not_rebroadcast(self) -> None:
        book = EpisodeBook(_TEST_THR)
        f = [Factor("price", "down", -2.0, "pct", 5.0, "1m")]
        self.assertIsNotNone(book.ingest(1, "ETH", f, _T0, liquidity_ok=True))
        self.assertIsNone(book.ingest(1, "ETH", f, _T0 + 1, liquidity_ok=True))

    def test_closed_episode_needs_escalation_to_reopen(self) -> None:
        book = EpisodeBook(_TEST_THR)
        f = [Factor("price", "down", -2.0, "pct", 5.0, "1m")]
        book.ingest(1, "ETH", f, _T0, liquidity_ok=True)
        book.ingest(1, "ETH", [], _T0 + 200, liquidity_ok=True)
        self.assertIsNone(book.ingest(1, "ETH", f, _T0 + 210, liquidity_ok=True))
        bigger = [Factor("price", "down", -4.0, "pct", 8.0, "1m")]
        self.assertIsNotNone(book.ingest(1, "ETH", bigger, _T0 + 220, liquidity_ok=True))

    def test_global_rate_cap(self) -> None:
        thr = AlertSettings(max_new_per_min=2)
        book = EpisodeBook(thr)
        f = [Factor("price", "down", -2.0, "pct", 5.0, "1m")]
        opened = [book.ingest(mi, f"M{mi}", f, _T0, liquidity_ok=True) for mi in range(1, 5)]
        self.assertEqual(sum(ev is not None for ev in opened), 2)

    def test_board_rows_expire(self) -> None:
        book = EpisodeBook(_TEST_THR)
        book.ingest(1, "ETH", [Factor("price", "down", -2.0, "pct", 5.0, "1m")], _T0, liquidity_ok=True)
        self.assertEqual(len(book.board_rows(_T0 + 1)), 1)
        self.assertEqual(book.board_rows(_T0 + _TEST_THR.board_ttl_s + 1), [])


class LiquidationTest(unittest.TestCase):
    def test_liq_cluster_scored_against_open_interest(self) -> None:
        h = Harness()
        h.seed_snapshots(1, [_snap(_T0, oi=5_000_000.0)])
        h.det._symbols[1] = "ETH"
        items = [
            {
                "market_index": 1,
                "trade_id": f"1:liquidation:{i}",
                "usd_amount": "60000",
                "side": "sell",
                "timestamp": int((_T0 - 8) * 1000),
            }
            for i in range(8)
        ]
        with patch("mayedge.alerts.time.time", return_value=_T0):
            h.det.on_liquidations(items)
        events = [e for m in h.messages for e in m.get("events", [])]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["setup"], "long_flush")
        self.assertEqual(events[0]["factors"][0]["kind"], "liq_cluster")


if __name__ == "__main__":
    unittest.main()
