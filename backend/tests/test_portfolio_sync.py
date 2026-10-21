"""Portfolio history (docs/portfolio-rules.md H1–H6), against a fake venue."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Any
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient

from mayedge import db as store
from mayedge.api import responses
from mayedge.api.app import create_app
from mayedge.config import settings
from mayedge.persist_portfolio import (
    portfolio_backfilled,
    portfolio_buckets,
    portfolio_put_buckets,
)
from mayedge.portfolio import DAY_MS, HOUR_MS, days, history
from mayedge.portfolio_sync import HorizonReached, closed, sync_once

# Now is 13:20 UTC; the account opened 10 days ago at 00:00 UTC.
NOW = 1_792_000_000_000 - 1_792_000_000_000 % DAY_MS + 13 * HOUR_MS + 20 * 60_000
OPENED = NOW - NOW % DAY_MS - 10 * DAY_MS
DEPOSIT_AT = OPENED + 3 * DAY_MS  # a $500 deposit into Perps


def bucket(ts_ms: int, mode: str) -> dict[str, Any]:
    """A cumulative bucket: $1 of trading PnL an hour since the open, and two deposits."""
    if ts_ms < OPENED:
        return {"timestamp": ts_ms // 1000, "trade_pnl": 0, "inflow": 0, "outflow": 0, "volume": 0}
    pnl = (ts_ms - OPENED) // HOUR_MS
    inflow = 1000 + (500 if ts_ms >= DEPOSIT_AT else 0)
    trade = pnl + inflow if mode == "values" else pnl
    return {
        "timestamp": ts_ms // 1000,
        "trade_pnl": trade,
        "inflow": inflow,
        "outflow": 0,
        "volume": 3,
    }


class FakeVenue:
    def __init__(self, now_ms: int) -> None:
        self.now = now_ms
        self.calls: list[tuple[str, str, int, int]] = []
        self.fail_after: int | None = None
        # The venue's hourly lookback; older windows answer code 22403.
        self.hourly_horizon_ms: int | None = None

    async def fetch(
        self, resolution: str, mode: str, start_ms: int, end_ms: int, count: int
    ) -> list[dict[str, Any]]:
        if self.fail_after is not None and len(self.calls) >= self.fail_after:
            raise RuntimeError("venue down")
        if (
            resolution == "1h"
            and self.hourly_horizon_ms is not None
            and start_ms < self.now - self.hourly_horizon_ms
        ):
            raise HorizonReached(resolution)
        self.calls.append((resolution, mode, start_ms, end_ms))
        step = HOUR_MS if resolution == "1h" else DAY_MS
        first = start_ms - start_ms % step
        rows = [bucket(ts, mode) for ts in range(first, min(end_ms, self.now) + 1, step)]
        # The venue's last bucket is the partial one, stamped at the request.
        if end_ms >= self.now:
            rows.append(bucket(self.now, mode))
        return rows


class StoreCase(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old = settings.db_path
        store.close_db()
        settings.db_path = str(Path(self.tmp.name) / "portfolio.db")
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        store.close_db()
        settings.db_path = self.old


class SyncTests(StoreCase):
    async def test_only_closed_buckets_are_stored(self) -> None:
        self.assertEqual(
            [
                ts
                for ts, _ in closed(
                    [bucket(NOW, "pnl"), bucket(NOW - NOW % HOUR_MS, "pnl")], HOUR_MS
                )
            ],
            [NOW - NOW % HOUR_MS],
        )
        venue = FakeVenue(NOW)
        await sync_once(venue.fetch, enabled=True, now_ms=NOW)
        stamps = [row["timestamp"] * 1000 for row in portfolio_buckets("1h", "pnl")]
        self.assertTrue(stamps)
        self.assertTrue(all(ts % HOUR_MS == 0 for ts in stamps))
        self.assertNotIn(NOW, stamps)
        self.assertTrue(
            all(row["timestamp"] * 1000 % DAY_MS == 0 for row in portfolio_buckets("1d", "values"))
        )

    async def test_a_bucket_answered_again_replaces_the_stored_one(self) -> None:
        ts = NOW - NOW % HOUR_MS
        portfolio_put_buckets("1h", "pnl", [(ts, {"timestamp": ts // 1000, "trade_pnl": 1})])
        portfolio_put_buckets("1h", "pnl", [(ts, {"timestamp": ts // 1000, "trade_pnl": 2})])
        self.assertEqual([row["trade_pnl"] for row in portfolio_buckets("1h", "pnl")], [2])

    async def test_backfill_walks_back_until_the_account_did_not_exist(self) -> None:
        venue = FakeVenue(NOW)
        await sync_once(venue.fetch, enabled=True, now_ms=NOW)
        self.assertTrue(portfolio_backfilled("1h"))
        self.assertTrue(portfolio_backfilled("1d"))
        hourly = portfolio_buckets("1h", "pnl")
        self.assertLessEqual(hourly[0]["timestamp"] * 1000, OPENED)
        # It stopped at the first all-zero window, not at the 90-day horizon.
        self.assertGreater(hourly[0]["timestamp"] * 1000, NOW - 90 * DAY_MS)
        self.assertGreater(
            portfolio_buckets("1d", "pnl")[0]["timestamp"] * 1000, NOW - 730 * DAY_MS
        )

    async def test_backfill_stops_at_the_venues_horizon(self) -> None:
        venue = FakeVenue(NOW)
        venue.hourly_horizon_ms = 7 * DAY_MS
        await sync_once(venue.fetch, enabled=True, now_ms=NOW)
        self.assertTrue(portfolio_backfilled("1h"))
        oldest = portfolio_buckets("1h", "pnl")[0]["timestamp"] * 1000
        self.assertGreaterEqual(oldest, NOW - 7 * DAY_MS)
        self.assertGreater(
            oldest, OPENED, "the hourly series ends at the venue's horizon, not the account's open"
        )
        # Daily buckets still reach back to the open.
        self.assertLessEqual(portfolio_buckets("1d", "pnl")[0]["timestamp"] * 1000, OPENED)

    async def test_an_interrupted_backfill_carries_on_from_the_oldest_bucket(self) -> None:
        venue = FakeVenue(NOW)
        venue.fail_after = 8
        with self.assertRaises(RuntimeError):
            await sync_once(venue.fetch, enabled=True, now_ms=NOW)
        self.assertFalse(portfolio_backfilled("1h"))
        cut = portfolio_buckets("1h", "pnl")[0]["timestamp"] * 1000
        self.assertGreater(cut, OPENED)
        venue.fail_after = None
        venue.calls.clear()
        await sync_once(venue.fetch, enabled=True, now_ms=NOW)
        self.assertTrue(portfolio_backfilled("1h"))
        self.assertLessEqual(portfolio_buckets("1h", "pnl")[0]["timestamp"] * 1000, OPENED)
        # The second sync picked up below the cut, not from now again.
        backfill = [c for c in venue.calls if c[0] == "1h" and c[3] <= cut]
        self.assertTrue(backfill)

    async def test_a_sync_after_the_backfill_reads_only_the_latest_buckets(self) -> None:
        venue = FakeVenue(NOW)
        await sync_once(venue.fetch, enabled=True, now_ms=NOW)
        venue.calls.clear()
        later = NOW + 5 * 60_000
        venue.now = later
        await sync_once(venue.fetch, enabled=True, now_ms=later)
        self.assertEqual(len(venue.calls), 4, "one window per resolution, in both modes")
        hourly = [c for c in venue.calls if c[0] == "1h"]
        self.assertTrue(all(later - c[2] <= 4 * HOUR_MS for c in hourly))

    async def test_nothing_syncs_when_trading_is_off(self) -> None:
        venue = FakeVenue(NOW)
        self.assertEqual(
            await sync_once(venue.fetch, enabled=False, now_ms=NOW), {"started": False}
        )
        self.assertEqual(venue.calls, [])


def _series(step: int, start: int, end: int, mode: str) -> list[dict[str, Any]]:
    return [bucket(ts, mode) for ts in range(start - start % step, end + 1, step)]


class HistoryTests(TestCase):
    def test_a_flow_marker_is_a_move_in_net_flows(self) -> None:
        start, end = DEPOSIT_AT - 3 * HOUR_MS, DEPOSIT_AT + 3 * HOUR_MS
        out = history(_series(HOUR_MS, start, end, "values"), _series(HOUR_MS, start, end, "pnl"))
        self.assertEqual(out["flows"], [{"ts": DEPOSIT_AT, "kind": "perps", "amount": "500"}])
        before, after = out["points"][2], out["points"][3]
        self.assertEqual(
            int(after["perps"]) - int(before["perps"]), 501, "the deposit and an hour of PnL"
        )

    def test_days_are_utc_days(self) -> None:
        daily = _series(DAY_MS, OPENED, NOW, "pnl")
        hourly = _series(HOUR_MS, NOW - 2 * DAY_MS, NOW, "pnl")
        rows = days(hourly, daily, since_ms=NOW - 3 * DAY_MS, now_ms=NOW)
        self.assertTrue(all(row["start"] % DAY_MS == 0 for row in rows))
        self.assertEqual(
            [row["day"] for row in rows][-1], time.strftime("%Y-%m-%d", time.gmtime(NOW / 1000))
        )
        full = rows[-2]
        self.assertEqual(
            full["kinds"]["perps"], "24", "$1 an hour over a whole day; the deposit is not in it"
        )
        # The deposit day's change leaves the $500 out.
        deposit_day = next(
            row
            for row in days(hourly, daily, since_ms=OPENED, now_ms=NOW)
            if row["start"] == DEPOSIT_AT
        )
        self.assertEqual(deposit_day["kinds"]["perps"], "24")

    def test_today_runs_from_utc_midnight_to_the_last_hourly_bucket(self) -> None:
        daily = _series(DAY_MS, OPENED, NOW, "pnl")
        hourly = _series(HOUR_MS, NOW - DAY_MS, NOW, "pnl")
        today = days(hourly, daily, since_ms=NOW - DAY_MS, now_ms=NOW)[-1]
        self.assertEqual(today["start"], NOW - NOW % DAY_MS)
        # 00:00 to the 13:00 bucket is 13 hours.
        self.assertEqual(today["kinds"]["perps"], "13")
        # Before the daily bucket for today is stored, today opens on the hourly one at 00:00.
        no_daily_today = [row for row in daily if row["timestamp"] * 1000 < NOW - NOW % DAY_MS]
        self.assertEqual(
            days(hourly, no_daily_today, since_ms=NOW - DAY_MS, now_ms=NOW)[-1]["kinds"]["perps"],
            "13",
        )


class RouteTests(StoreCase):
    async def test_history_is_hourly_for_a_week_and_daily_beyond(self) -> None:
        venue = FakeVenue(NOW)
        await sync_once(venue.fetch, enabled=True, now_ms=NOW)
        app = create_app()
        with patch("mayedge.api.routes.portfolio.time.time", lambda: NOW / 1000):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://localhost"
            ) as client:
                week = (await client.get("/api/portfolio/history", params={"range": "7d"})).json()
                self.assertEqual(week["resolution"], "1h")
                responses.PortfolioHistory.model_validate(week)
                self.assertGreater(len(week["points"]), 7 * 24 - 2)
                month = (await client.get("/api/portfolio/history", params={"range": "30d"})).json()
                self.assertEqual(month["resolution"], "1d")
                every = (await client.get("/api/portfolio/history", params={"range": "all"})).json()
                self.assertEqual(every["resolution"], "1d")
                # From before the account: the opening deposit, then the later one.
                self.assertEqual(
                    [(f["ts"], f["amount"]) for f in every["flows"]],
                    [(OPENED, "1000"), (DEPOSIT_AT, "500")],
                )
                daily = (await client.get("/api/portfolio/days", params={"range": "7d"})).json()
                self.assertNotIn("tz", daily)
                self.assertTrue(daily["days"])
                responses.PortfolioDays.model_validate(daily)
                bad = await client.get("/api/portfolio/days", params={"range": "1d"})
                self.assertEqual(bad.status_code, 400)
