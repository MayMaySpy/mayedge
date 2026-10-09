from __future__ import annotations

import unittest
from collections import deque
from pathlib import Path
from typing import Any
from unittest.mock import patch

from mayedge.alert_outcomes import MemoryOutcomeStore, OutcomeBook
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
        gw._apply_market_stats({
            "market_stats": {
                "market_id": 1,
                "mark_price": "2000",
                "open_interest": "5000000",
                "best_bid_price": "1998",
                "mid_price": "2000",
            }
        })
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
        self.assertEqual(thr.vol_score_cap, 6.0)
        self.assertEqual(thr.price_recent_bars, 30)
        self.assertEqual(thr.broad_min_markets, 15)
        self.assertEqual(thr.outcome_horizons, (5, 15))


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
        s = composite_score([
            Factor("price", "up", 1.0, "pct", 6.0),
            Factor("volume", "up", 4.0, "x", 4.0),
        ])
        self.assertAlmostEqual(s, 8.0)

    def test_factors_merge_into_one_row_with_stable_id(self) -> None:
        book = EpisodeBook(_TEST_THR)
        ev1 = book.ingest(
            1, "ETH", [Factor("price", "down", -2.0, "pct", 5.0, "1m")], _T0, liquidity_ok=True
        )
        ev2 = book.ingest(
            1, "ETH", [Factor("volume", "up", 6.0, "x", 5.0, "1m")], _T0 + 1, liquidity_ok=True
        )
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
        book.ingest(
            1, "ETH", [Factor("price", "down", -2.0, "pct", 5.0, "1m")], _T0, liquidity_ok=True
        )
        self.assertEqual(len(book.board_rows(_T0 + 1)), 1)
        self.assertEqual(book.board_rows(_T0 + _TEST_THR.board_ttl_s + 1), [])


def _seed_board(
    h: Harness,
    n: int,
    closes: list[float],
    *,
    last: float,
    holdout: int | None = None,
    holdout_last: float | None = None,
) -> None:
    for mi in range(1, n + 1):
        px = holdout_last if mi == holdout and holdout_last is not None else last
        h.det.seed_minute_bars(mi, _bars(closes))
        h.seed_snapshots(
            mi,
            [
                _snap(_T0 - 400, last=100.0, mark=100.0),
                _snap(_T0 - 1, last=px, mark=px),
            ],
        )


class NoiseRatioTest(unittest.TestCase):
    def test_a_board_dump_is_one_broad_row(self) -> None:
        h = Harness()
        _seed_board(h, 20, _wiggle(60, 0.1), last=97.0)
        events = h.tick(_meta(market_index=1, symbol="ETH", last_trade_price=97.0, mark_price=97.0))
        self.assertEqual([e["market_index"] for e in events], [-1])
        self.assertEqual(events[0]["setup"], "broad_down")
        self.assertEqual(events[0]["symbol"], "BTC")
        self.assertIn("20/20", events[0]["note"])

    def test_a_market_that_falls_less_than_the_board_holds_up(self) -> None:
        h = Harness()
        _seed_board(h, 20, _wiggle(60, 0.1), last=97.0, holdout=20, holdout_last=99.0)
        events = h.tick(
            _meta(market_index=20, symbol="ZRO", last_trade_price=99.0, mark_price=99.0)
        )
        setups = {(e["setup"], e["market_index"]) for e in events}
        self.assertIn(("holds_up", 20), setups)
        self.assertIn(("broad_down", -1), setups)
        self.assertTrue(all(e["market_index"] in (20, -1) for e in events))

    def test_a_bounce_after_a_wild_half_hour_stays_quiet(self) -> None:
        def path(calm: int, wild: int) -> list[float]:
            px = [100.0]
            for i in range(calm):
                px.append(px[-1] * (1 + (0.05 if i % 2 else -0.05) / 100.0))
            for i in range(wild):
                px.append(px[-1] * (1 + (2.0 if i % 2 else -2.0) / 100.0))
            return px

        wild = Harness()
        closes = path(40, 40)
        wild.det.seed_minute_bars(1, _bars(closes))
        last = closes[-1]
        wild.seed_snapshots(1, [_snap(_T0 - 65, last=last, mark=last, mid=last)])
        bounced = last * 1.007
        self.assertEqual(
            wild.tick(_meta(last_trade_price=bounced, mark_price=bounced, mid_price=bounced)),
            [],
        )

        calm = Harness()
        closes = path(80, 0)
        calm.det.seed_minute_bars(1, _bars(closes))
        last = closes[-1]
        calm.seed_snapshots(1, [_snap(_T0 - 65, last=last, mark=last, mid=last)])
        bounced = last * 1.007
        events = calm.tick(_meta(last_trade_price=bounced, mark_price=bounced, mid_price=bounced))
        self.assertEqual([e["setup"] for e in events], ["pump"])

    def test_thin_tape_uses_the_day_volume_floor(self) -> None:
        h = Harness()
        bars = _bars([100.0] * 40, vol=0.01)
        bars[-1].volume = 500.0
        h.det.seed_minute_bars(1, bars)
        h.seed_snapshots(1, [_snap(_T0 - 65)])
        events = h.tick(_meta())
        volumes = [f for e in events for f in (e["factors"] or []) if f["kind"] == "volume"]
        self.assertEqual(len(volumes), 1)
        self.assertLess(volumes[0]["value"], 20)

    def test_a_board_wide_volume_surge_raises_no_volume_alert(self) -> None:
        h = Harness()
        bars = _bars([100.0] * 40, vol=100.0)
        bars[-1].volume = 1_000.0
        for mi in range(1, 21):
            h.det.seed_minute_bars(
                mi, [Candle(b.time, b.open, b.high, b.low, b.close, b.volume) for b in bars]
            )
            h.seed_snapshots(mi, [_snap(_T0 - 1)])
        self.assertEqual(h.tick(_meta(market_index=1)), [])

    def test_volume_alone_stays_notable(self) -> None:
        h = Harness()
        bars = _bars([100.0] * 40, vol=1_000.0)
        bars[-1].volume = 1_000_000.0
        h.det.seed_minute_bars(1, bars)
        h.seed_snapshots(1, [_snap(_T0 - 65)])
        events = h.tick(_meta())
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["severity"], 2)
        self.assertLessEqual(max(f["score"] for f in events[0]["factors"]), 6.0)

    def test_follow_through_resolves_after_the_horizon_bars(self) -> None:
        h = Harness()
        h.det._outcomes = OutcomeBook(store=MemoryOutcomeStore())
        closes = _wiggle(40, 0.05)
        h.det.seed_minute_bars(1, _bars(closes))
        h.seed_snapshots(1, [_snap(_T0 - 65)])
        events = h.tick(_meta(last_trade_price=101.5, mark_price=101.5))
        self.assertEqual([e["setup"] for e in events], ["pump"])
        entry_bar = _BAR0 + 39 * 60
        entry_close = closes[-1]
        future = [
            Candle(
                time=entry_bar + step * 60,
                open=entry_close * 1.02,
                high=entry_close * 1.02,
                low=entry_close * 1.02,
                close=entry_close * 1.02,
                volume=1_000,
            )
            for step in range(1, 17)
        ]
        h.det.on_minute_bars(1, future)
        with patch("mayedge.alerts.time.time", return_value=_T0 + 3600):
            stats = h.det.outcome_stats(hours=24)
        self.assertEqual(stats["setups"][0]["setup"], "pump")
        self.assertEqual(stats["setups"][0]["n"], 1)
        self.assertEqual(stats["setups"][0]["hit_5m"], 1.0)
        self.assertEqual(stats["setups"][0]["hit_15m"], 1.0)

    def test_idle_minute_bars_do_not_rebuild_broad_returns(self) -> None:
        h = Harness()
        for mi in range(1, 5):
            h.det.seed_minute_bars(mi, _bars(_wiggle(40, 0.05)))
        with patch.object(h.det._minute, "broad_returns", wraps=h.det._minute.broad_returns) as spy:
            h.det.on_minute_bars(1, [_bars([100.0])[-1]])
            spy.assert_not_called()

    def test_pending_outcome_reuses_the_broad_return_cache(self) -> None:
        h = Harness()
        h.det.seed_minute_bars(1, _bars(_wiggle(40, 0.05)))
        h.det._outcomes.open(
            episode_id="sig-1",
            market_index=1,
            symbol="ETH",
            setup="pump",
            direction="up",
            entry_bar=_BAR0,
            entry_close=100.0,
            beta=0.0,
            opened_at=int(_T0 * 1000),
        )
        with (
            patch.object(h.det._minute, "broad_returns", wraps=h.det._minute.broad_returns) as spy,
            patch("mayedge.alerts.time.time", return_value=_T0),
        ):
            h.det.on_minute_bars(1, [_bars([100.0])[-1]])
            h.det.on_minute_bars(1, [_bars([101.0])[-1]])
        self.assertEqual(spy.call_count, 1)

    def test_live_moves_are_cached_for_a_second(self) -> None:
        h = Harness()
        h.seed_snapshots(1, [_snap(_T0 - 120), _snap(_T0 - 1)])
        h.det._live_moves(60.0, _T0)
        with patch.object(h.det, "_find_baseline", wraps=h.det._find_baseline) as spy:
            h.det._live_moves(60.0, _T0 + 0.5)
            spy.assert_not_called()
            h.det._live_moves(300.0, _T0 + 0.5)
            self.assertGreater(spy.call_count, 0)
        with patch.object(h.det, "_find_baseline", wraps=h.det._find_baseline) as again:
            h.det._live_moves(60.0, _T0 + 1.1)
            self.assertGreater(again.call_count, 0)


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
