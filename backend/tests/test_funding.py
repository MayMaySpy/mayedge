"""Stored funding: rule F3 in docs/alert-rules.md."""

from __future__ import annotations

import asyncio
import unittest
from collections import deque
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from mayedge import db as store
from mayedge.alert_log import AlertLog, MemoryLogStore
from mayedge.alerts import AlertDetector, AlertSettings, MarketSnapshot
from mayedge.config import settings
from mayedge.funding_backfill import (
    DayReading,
    Reading,
    backfill_funding,
    backfill_funding_days,
    calibrate,
    calibrate_days,
    full_days,
    parse_venue_fundings,
)
from mayedge.lighter.models import MarketMeta
from mayedge.persist_funding import funding_print_rows, funding_sample_rows

_NOW = 1_800_000_000.0
_MINUTE = int(_NOW) // 60


def _perp(market_index: int, funding: float | None, market_type: str = "perp") -> MarketMeta:
    return MarketMeta(
        market_index, f"M{market_index}", 2, 4, 0.0, 0.0, market_type=market_type, funding_rate=funding
    )


class FundingStoreTest(unittest.TestCase):
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

    def test_a_rate_of_zero_is_a_rate(self) -> None:
        rows = funding_sample_rows([_perp(1, 0.0), _perp(2, None), _perp(3, 0.01, "spot")])
        self.assertEqual(rows, [{"market_index": 1, "funding": 0.0}])

    def test_minutes_past_retention_are_dropped(self) -> None:
        row = [{"market_index": 1, "funding": 0.001}]
        store.flush_funding(row, minute_index=_MINUTE - 100, keep_minutes=60)
        store.flush_funding(row, minute_index=_MINUTE - 10, keep_minutes=60)
        store.flush_funding(row, minute_index=_MINUTE, keep_minutes=60)
        kept = store.recent_funding(0)[1]
        self.assertEqual([minute for minute, _rate in kept], [_MINUTE - 10, _MINUTE])

    def test_funding_survives_a_restart(self) -> None:
        # A day at 0.001, written by the run before this one.
        for back in range(40, 0, -1):
            store.flush_funding(
                [{"market_index": 1, "funding": 0.001}], minute_index=_MINUTE - back, keep_minutes=4320
            )
        det = AlertDetector(
            lambda message: None, AlertSettings(), log=AlertLog(store=MemoryLogStore())
        )
        det.seed_levels("funding", store.recent_funding(_MINUTE - 1440))
        det._symbols[1] = "ETH"
        det._snapshots[1] = deque([
            MarketSnapshot(
                ts=_NOW - 1,
                mark=100.0,
                last=100.0,
                index=100.0,
                mid=100.0,
                bid=99.99,
                ask=100.01,
                oi=5_000_000.0,
                vol_quote=10_000_000.0,
                funding=0.012,
                premium=0.0,
            )
        ])
        with patch("mayedge.alerts.time.time", return_value=_NOW):
            strip = det.funding_extremes()
        # Extreme on the first print after boot, with no minutes of its own yet.
        self.assertEqual([(row["symbol"], row["z"]) for row in strip], [("ETH", 5.5)])


_HOUR = int(_NOW) // 3600


class _StoreCase(unittest.TestCase):
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

    def _print(self, hour: int, rate: float) -> None:
        store.flush_funding_prints([{"market_index": 1, "hour_index": hour, "rate": rate}])


class FundingHistoryTest(_StoreCase):
    def test_a_print_is_filed_under_the_hour_it_paid_for(self) -> None:
        meta = _perp(1, 0.002)
        meta.settled_funding_rate = 0.001
        meta.funding_timestamp = _HOUR * 3600 * 1000
        spot = _perp(2, 0.002, "spot")
        spot.settled_funding_rate = 0.001
        spot.funding_timestamp = _HOUR * 3600 * 1000
        rows = funding_print_rows([meta, spot, _perp(3, 0.002)])
        self.assertEqual(rows, [{"market_index": 1, "hour_index": _HOUR - 1, "rate": 0.001}])

    def test_prints_are_kept_past_minute_retention(self) -> None:
        self._print(_HOUR - 24 * 400, 0.003)
        store.flush_funding(
            [{"market_index": 1, "funding": 0.001}], minute_index=_MINUTE, keep_minutes=60
        )
        got = store.list_funding(1, resolution="1d", count=500, now=_NOW)
        self.assertEqual(got[0], {"time": (_HOUR - 24 * 400) * 3600 // 86400 * 86400, "rate": 0.003, "settled": True})

    def test_a_bucket_of_prints_is_their_mean(self) -> None:
        start = _HOUR // 4 * 4 - 4
        for back, rate in enumerate([0.001, 0.002, 0.003, 0.006]):
            self._print(start + back, rate)
        got = store.list_funding(1, resolution="4h", count=10, now=_NOW)
        self.assertEqual(got, [{"time": start * 3600, "rate": 0.003, "settled": True}])

    def test_the_hour_not_yet_settled_is_the_estimate(self) -> None:
        self._print(_HOUR - 1, 0.001)
        minute = _HOUR * 60
        for m, rate in [(minute - 30, 0.009), (minute + 1, 0.004), (minute + 2, 0.005)]:
            store.flush_funding(
                [{"market_index": 1, "funding": rate}], minute_index=m, keep_minutes=10_000
            )
        got = store.list_funding(1, resolution="1h", count=3, now=_HOUR * 3600 + 300)
        self.assertEqual(
            got,
            [
                {"time": (_HOUR - 1) * 3600, "rate": 0.001, "settled": True},
                {"time": _HOUR * 3600, "rate": 0.005, "settled": False},
            ],
        )
        minutes = store.list_funding(1, resolution="15m", count=8, now=_HOUR * 3600 + 300)
        self.assertEqual([row["settled"] for row in minutes], [True, True, True, True, False])
        self.assertEqual(minutes[1]["rate"], 0.001)

    def test_resolution_is_checked(self) -> None:
        with self.assertRaises(ValueError):
            store.list_funding(1, resolution="2h", count=10)


class FundingAverageTest(_StoreCase):
    def test_each_window_counts_its_own_hours(self) -> None:
        self._print(_HOUR - 1, 0.002)
        self._print(_HOUR - 2, 0.004)
        self._print(_HOUR - 24 * 20, 0.009)
        self._print(_HOUR - 24 * 400, 1.0)
        self._print(_HOUR, 5.0)  # the hour in progress is not settled
        got = store.funding_averages(1, now=_NOW)
        by = {w["label"]: w for w in got["windows"]}
        self.assertEqual(by["7d"]["hours"], 2)
        self.assertAlmostEqual(by["7d"]["rate"], 0.003)
        self.assertEqual(by["30d"]["hours"], 3)
        self.assertAlmostEqual(by["30d"]["rate"], 0.005)
        self.assertEqual(by["1y"]["hours"], 3)
        self.assertEqual(got["first_time"], (_HOUR - 24 * 20) * 3600)

    def test_no_prints_is_no_average(self) -> None:
        got = store.funding_averages(1, now=_NOW)
        self.assertEqual([w["rate"] for w in got["windows"]], [None, None, None])
        self.assertIsNone(got["first_time"])


def _venue(hour: int, rate: float, direction: str, *, settle_stamp: bool = True) -> dict:
    stamp = (hour + 1 if settle_stamp else hour) * 3600
    return {"timestamp": stamp, "value": "0", "rate": str(rate), "direction": direction}


class FundingCalibrationTest(unittest.TestCase):
    def test_finds_the_reading_that_matches_the_desk(self) -> None:
        # Venue: a fraction, unsigned, stamped at settlement. Desk: signed percent.
        local = {_HOUR - 3: 0.0012, _HOUR - 2: -0.003, _HOUR - 1: 0.0005}
        rows = parse_venue_fundings(
            [
                _venue(_HOUR - 3, 0.000012, "long"),
                _venue(_HOUR - 2, 0.00003, "short"),
                _venue(_HOUR - 1, 0.000005, "long"),
            ]
        )
        self.assertEqual(calibrate([(rows, local)]), Reading(-1, 100.0, "direction"))

    def test_refuses_when_nothing_matches(self) -> None:
        local = {_HOUR - 3: 0.5, _HOUR - 2: 0.5, _HOUR - 1: 0.5}
        rows = parse_venue_fundings([_venue(h, 0.001, "long") for h in local])
        self.assertIsNone(calibrate([(rows, local)]))

    def test_refuses_too_few_overlaps(self) -> None:
        local = {_HOUR - 1: 0.0012}
        rows = parse_venue_fundings([_venue(_HOUR - 1, 0.0012, "long")])
        self.assertIsNone(calibrate([(rows, local)]))

    def test_milliseconds_are_read_as_seconds(self) -> None:
        rows = parse_venue_fundings([{"timestamp": 1_800_000_000_000, "rate": "0.1", "direction": "long"}])
        self.assertEqual(rows[0].time_s, 1_800_000_000)


class FundingBackfillTest(_StoreCase):
    def test_writes_a_year_once_and_keeps_live_prints(self) -> None:
        live = {_HOUR - 3: 0.0012, _HOUR - 2: -0.003, _HOUR - 1: 0.0005}
        for hour, rate in live.items():
            self._print(hour, rate)
        venue = {h: (abs(r), "long" if r > 0 else "short") for h, r in live.items()}
        for back in range(4, 24 * 400):
            venue[_HOUR - back] = (0.001, "short")
        venue[_HOUR - 1] = (0.0009, "long")  # disagrees with the live print; live wins
        calls: list[tuple[int, int, int]] = []

        async def fetch(idx: int, end_ms: int, count: int, resolution: str) -> list[dict]:
            calls.append((idx, end_ms, count))
            hours = sorted((h for h in venue if (h + 1) * 3600 * 1000 <= end_ms), reverse=True)[:count]
            return [_venue(h, *venue[h]) for h in hours]

        perp = _perp(1, 0.001)
        got = asyncio.run(backfill_funding([perp], fetch, now=_NOW))
        # Calibration sees one mismatch, so it refuses; fix the venue and retry.
        self.assertEqual(got, 0)
        venue[_HOUR - 1] = (0.0005, "long")
        got = asyncio.run(backfill_funding([perp], fetch, now=_NOW))
        self.assertEqual(got, 365 * 24 - 3)
        hist = store.list_funding(1, resolution="1d", count=500, now=_NOW)
        self.assertAlmostEqual(hist[1]["rate"], -0.001)
        self.assertTrue(store.funding_backfill_done(1))
        calls.clear()
        self.assertEqual(asyncio.run(backfill_funding([perp], fetch, now=_NOW)), 0)
        self.assertEqual(len(calls), 1)  # the calibration probe only


_DAY = int(_NOW) // 86400


def _day_rate(day: int, hour: int) -> float:
    """Hourly rates that differ by day and by hour, so readings can be told apart."""
    # Every third day leans negative, so the sign of a venue day is tested too.
    return round(0.0001 * ((day * 7 + hour * 3) % 23 - (16 if day % 3 == 0 else 8)), 6)


class FundingDayStoreTest(_StoreCase):
    def _hours(self, day: int, count: int = 24, rate: float | None = None) -> None:
        for hour in range(24 - count, 24):
            self._print(day * 24 + hour, rate if rate is not None else _day_rate(day, hour))

    def test_a_day_short_of_24_prints_takes_the_venue_day(self) -> None:
        self._hours(_DAY - 3, rate=0.001)  # full: prints win over the venue row
        self._hours(_DAY - 2, count=11, rate=0.005)  # partial: the venue row wins
        store.insert_funding_days(
            [
                {"market_index": 1, "day_index": _DAY - 3, "rate": 0.9},
                {"market_index": 1, "day_index": _DAY - 2, "rate": 0.002},
                {"market_index": 1, "day_index": _DAY - 200, "rate": -0.003},
                {"market_index": 1, "day_index": _DAY, "rate": 0.7},  # today is never a day
            ]
        )
        bars = store.list_funding(1, resolution="1d", count=500, now=_NOW)
        self.assertEqual(
            [(b["time"] // 86400, b["rate"]) for b in bars],
            [(_DAY - 200, -0.003), (_DAY - 3, 0.001), (_DAY - 2, 0.002)],
        )
        self.assertTrue(all(b["settled"] for b in bars))
        # Days never fill hourly charts.
        hours = store.list_funding(1, resolution="1h", count=500, now=_NOW)
        self.assertEqual(len(hours), 24 + 11)

    def test_the_year_counts_a_venue_day_as_24_hours(self) -> None:
        for back in range(1, 63):
            self._hours(_DAY - back, rate=0.001)
        store.insert_funding_days(
            [{"market_index": 1, "day_index": _DAY - back, "rate": 0.002} for back in range(63, 364)]
        )
        got = store.funding_averages(1, now=_DAY * 86400)
        by = {w["label"]: w for w in got["windows"]}
        self.assertEqual(by["30d"]["hours"], 30 * 24)
        self.assertAlmostEqual(by["30d"]["rate"], 0.001)
        self.assertEqual(by["1y"]["hours"], 363 * 24)
        self.assertEqual((by["30d"]["venue_days"], by["1y"]["venue_days"]), (0, 301))
        self.assertAlmostEqual(by["1y"]["rate"], (62 * 0.001 + 301 * 0.002) / 363)
        self.assertEqual(got["first_time"], (_DAY - 363) * 86400)


def _venue_day(day: int, value: float, *, end_stamp: bool = True) -> dict:
    stamp = (day + 1 if end_stamp else day) * 86400
    return {
        "timestamp": stamp,
        "value": "0",
        "rate": str(abs(value)),
        "direction": "long" if value >= 0 else "short",
    }


class FundingDayCalibrationTest(unittest.TestCase):
    def _local(self) -> dict:
        prints = {
            day * 24 + hour: _day_rate(day, hour)
            for day in range(_DAY - 10, _DAY)
            for hour in range(24)
        }
        return full_days(prints)

    def test_finds_a_venue_day_that_is_the_sum_stamped_at_its_end(self) -> None:
        local = self._local()
        rows = parse_venue_fundings([_venue_day(d, v["sum"]) for d, v in local.items()])
        self.assertEqual(calibrate_days([(rows, local)]), DayReading(-1, 1.0, "direction", "sum"))

    def test_finds_a_venue_day_that_is_the_mean_stamped_at_its_start(self) -> None:
        local = self._local()
        rows = parse_venue_fundings(
            [_venue_day(d, v["mean"], end_stamp=False) for d, v in local.items()]
        )
        reading = calibrate_days([(rows, local)])
        assert reading is not None
        self.assertEqual((reading.shift, reading.agg), (0, "mean"))

    def test_refuses_days_that_match_nothing(self) -> None:
        local = self._local()
        rows = parse_venue_fundings([_venue_day(d, 0.5) for d in local])
        self.assertIsNone(calibrate_days([(rows, local)]))


class FundingDayBackfillTest(_StoreCase):
    def _venue(self, value_of) -> dict:
        return {d: value_of(d) for d in range(_DAY - 700, _DAY)}

    def _run(self, venue: dict) -> tuple[int, list[str]]:
        calls: list[str] = []

        async def fetch(idx: int, end_ms: int, count: int, resolution: str) -> list[dict]:
            calls.append(resolution)
            days = sorted((d for d in venue if (d + 1) * 86400 * 1000 <= end_ms), reverse=True)
            return [_venue_day(d, venue[d]) for d in days[:count]]

        got = asyncio.run(backfill_funding_days([_perp(1, 0.001)], fetch, now=_NOW))
        return got, calls

    def _seed_hours(self) -> None:
        for day in range(_DAY - 10, _DAY):
            for hour in range(24):
                self._print(day * 24 + hour, _day_rate(day, hour))

    def test_writes_a_year_of_days_once(self) -> None:
        self._seed_hours()
        local = full_days(store.funding_prints_for(1, 0))
        venue = self._venue(lambda d: local[d]["sum"] if d in local else 0.024 * (1 if d % 2 else -1))
        got, calls = self._run(venue)
        self.assertEqual(got, 365)
        self.assertEqual(calls, ["1d", "1d"])  # probe, then the market's page
        bars = store.list_funding(1, resolution="1d", count=500, now=_NOW)
        self.assertEqual(len(bars), 365)
        self.assertAlmostEqual(bars[0]["rate"], 0.001 * (1 if (_DAY - 365) % 2 else -1))
        self.assertTrue(store.funding_days_backfill_done(1))
        got, calls = self._run(venue)
        self.assertEqual((got, calls), (0, ["1d"]))

    def test_a_venue_day_that_is_its_last_hour_is_not_stored(self) -> None:
        self._seed_hours()
        local = full_days(store.funding_prints_for(1, 0))
        venue = self._venue(lambda d: local[d]["last"] if d in local else 0.001)
        with self.assertLogs("mayedge.funding_backfill", level="WARNING") as logs:
            got, _calls = self._run(venue)
        self.assertEqual(got, 0)
        self.assertIn("last hour", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
