from __future__ import annotations

import time
import unittest
from pathlib import Path
from unittest.mock import patch

from mayedge.alerts import (
    ExploitDetector,
    ExploitThresholds,
    MarketSnapshot,
    SevPair,
    load_thresholds,
    thresholds_from_dict,
)
from mayedge.lighter.gateway import LighterGateway
from mayedge.lighter.models import MarketMeta

# Fast tests: no warmup, short cooldowns, low bars.
_TEST_THR = ExploitThresholds(
    cooldown_s=45.0,
    level_cooldown_s=45.0,
    min_severity=2,
    max_events_per_flush=50,
    warmup_s=0.0,
    oi_pct_1m=SevPair(3.0, 8.0),
    oi_pct_5m=SevPair(6.0, 15.0),
    spread_bps=SevPair(15.0, 50.0),
    liq_count=SevPair(3.0, 6.0),
    liq_usd=SevPair(100_000.0, 500_000.0),
    liq_window_s=120.0,
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
    )
    base.update(kwargs)
    return MarketMeta(**base)  # type: ignore[arg-type]


class ApplyMarketStatsTest(unittest.TestCase):
    def test_apply_market_stats_parses_extended_fields(self) -> None:
        gw = LighterGateway()
        gw._markets[1] = _meta()

        gw._apply_market_stats(
            {
                "market_stats": {
                    "market_id": 1,
                    "symbol": "ETH",
                    "mark_price": "2000",
                    "last_trade_price": "1999",
                    "index_price": "2001",
                    "open_interest": "5000000",
                    "open_interest_limit": "10000000",
                    "best_bid_price": "1998",
                    "best_ask_price": "2002",
                    "mid_price": "2000",
                    "premium": "-0.05",
                    "current_funding_rate": "0.001",
                    "funding_timestamp": 1786370400000,
                    "daily_quote_token_volume": 1000000,
                    "daily_base_token_volume": 500,
                    "daily_price_high": 2100,
                    "daily_price_low": 1900,
                    "daily_price_change": -1.2,
                }
            }
        )

        meta = gw._markets[1]
        self.assertEqual(meta.open_interest, 5_000_000.0)
        self.assertEqual(meta.best_bid_price, 1998.0)
        self.assertEqual(meta.best_ask_price, 2002.0)
        self.assertEqual(meta.mid_price, 2000.0)
        self.assertEqual(meta.premium, -0.05)
        self.assertEqual(meta.funding_timestamp, 1786370400000)
        self.assertEqual(meta.daily_price_high, 2100.0)
        self.assertEqual(meta.volume_base_24h, 500.0)


class ThresholdYamlTest(unittest.TestCase):
    def test_from_dict(self) -> None:
        thr = thresholds_from_dict(
            {
                "funding": {"hourly_pct": [0.2, 0.6]},
                "spread": {"bps": [40, 100]},
                "min_severity": 2,
            }
        )
        self.assertEqual(thr.funding_hourly_pct.sev2, 0.2)
        self.assertEqual(thr.spread_bps.sev3, 100.0)

    def test_load_repo_yaml(self) -> None:
        path = Path(__file__).resolve().parents[1] / "config" / "alerts.yaml"
        thr = load_thresholds(path)
        self.assertGreater(thr.funding_hourly_pct.sev2, 0)
        self.assertGreaterEqual(thr.min_severity, 2)


class ExploitDetectorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.events: list[dict] = []
        self.det = ExploitDetector(
            lambda msg: self.events.append(msg),
            thresholds=_TEST_THR,
        )

    def _seed_series(self, mi: int, snaps: list[MarketSnapshot]) -> None:
        series = self.det._snapshots.setdefault(mi, __import__("collections").deque(maxlen=1200))
        for s in snaps:
            series.append(s)
        if snaps:
            self.det._seen_since[mi] = snaps[0].ts

    def test_oi_shock_fires(self) -> None:
        now = time.time()
        self._seed_series(
            1,
            [
                MarketSnapshot(now - 65, 100, 100, 100, 100, 99, 101, 1000, 1e6, 0, 0),
            ],
        )
        meta = _meta(
            mark_price=100.0,
            last_trade_price=100.0,
            open_interest=1100.0,
            volume_24h=1e6,
        )
        with patch("mayedge.alerts.time.time", return_value=now):
            self.det.on_market_stats(meta)
            self.det.flush()

        kinds = {e["kind"] for batch in self.events for e in batch.get("events", [])}
        self.assertIn("oi", kinds)

    def test_young_baseline_does_not_fire_oi(self) -> None:
        now = time.time()
        self._seed_series(
            1,
            [MarketSnapshot(now - 5, 100, 100, 100, 100, 99, 101, 1000, 1e6, 0, 0)],
        )
        meta = _meta(
            mark_price=100.0,
            last_trade_price=100.0,
            open_interest=2000.0,
            volume_24h=1e6,
        )
        with patch("mayedge.alerts.time.time", return_value=now):
            self.det.on_market_stats(meta)
            self.det.flush()

        kinds = {e["kind"] for batch in self.events for e in batch.get("events", [])}
        self.assertNotIn("oi", kinds)

    def test_spread_blowout_fires(self) -> None:
        now = time.time()
        self._seed_series(
            1,
            [MarketSnapshot(now - 5, 100, 100, 100, 100, 99.5, 99.6, 1000, 1e6, 0, 0)],
        )
        meta = _meta(
            mark_price=100.0,
            last_trade_price=100.0,
            best_bid_price=98.0,
            best_ask_price=102.0,
            mid_price=100.0,
            open_interest=1000.0,
            volume_24h=1e6,
        )
        with patch("mayedge.alerts.time.time", return_value=now):
            self.det.on_market_stats(meta)
            self.det.flush()

        kinds = {e["kind"] for batch in self.events for e in batch.get("events", [])}
        self.assertIn("spread", kinds)

    def test_cooldown_suppresses_duplicate(self) -> None:
        now = time.time()
        self._seed_series(
            1,
            [MarketSnapshot(now - 65, 100, 100, 100, 100, 99, 101, 1000, 1e6, 0, 0)],
        )
        meta = _meta(
            mark_price=100.0,
            last_trade_price=100.0,
            best_bid_price=95.0,
            best_ask_price=105.0,
            mid_price=100.0,
            open_interest=1000.0,
            volume_24h=1e6,
        )
        with patch("mayedge.alerts.time.time", return_value=now):
            self.det.on_market_stats(meta)
            self.det.flush()
            self.det.on_market_stats(meta)
            self.det.flush()

        spread_events = [
            e for batch in self.events for e in batch.get("events", []) if e.get("kind") == "spread"
        ]
        self.assertEqual(len(spread_events), 1)

    def test_liq_cluster_fires(self) -> None:
        now = time.time()
        items = [
            {
                "market_index": 1,
                "symbol": "ETH",
                "usd_amount": "60000",
                "side": "sell",
                "price": "2000",
                "size": "30",
            }
            for _ in range(4)
        ]
        with patch("mayedge.alerts.time.time", return_value=now):
            self.det.on_liquidations(items)

        kinds = {e["kind"] for batch in self.events for e in batch.get("events", [])}
        self.assertIn("liq_cluster", kinds)

    def test_flush_caps_events(self) -> None:
        thr = ExploitThresholds(
            warmup_s=0.0,
            min_severity=2,
            max_events_per_flush=2,
            spread_bps=SevPair(1.0, 2.0),
            cooldown_s=0.0,
            level_cooldown_s=0.0,
        )
        det = ExploitDetector(lambda msg: self.events.append(msg), thresholds=thr)
        now = time.time()
        for i, mid in enumerate((1, 2, 3)):
            det._snapshots[mid] = __import__("collections").deque(
                [MarketSnapshot(now - 5, 100, 100, 100, 100, 99.9, 100.1, 1, 1, 0, 0)]
            )
            det._seen_since[mid] = now - 5
            meta = _meta(
                market_index=mid,
                symbol=f"M{mid}",
                mark_price=100.0,
                last_trade_price=100.0,
                best_bid_price=90.0,
                best_ask_price=110.0,
                mid_price=100.0,
            )
            with patch("mayedge.alerts.time.time", return_value=now + i):
                det.on_market_stats(meta)
        det.flush()
        n = sum(len(batch.get("events", [])) for batch in self.events)
        self.assertEqual(n, 2)


if __name__ == "__main__":
    unittest.main()
