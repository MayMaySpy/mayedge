"""The Portfolio now (docs/portfolio-rules.md N1–N7), on the Step 0 fixture."""

from __future__ import annotations

import copy
import json
from decimal import Decimal as D
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from mayedge import portfolio_venue
from mayedge.api.app import create_app
from mayedge.config import settings
from mayedge.portfolio import (
    DAY_MS,
    HOUR_MS,
    STAKING_POOL,
    OpenRefused,
    buckets,
    change_pct,
    day_open,
    kinds_now,
    mismatches,
    pool_row,
    portfolio_now,
    spot_rows,
)

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "portfolio_raw.json").read_text())
PNL = FIXTURE["pnl_1d"]
VALUES = FIXTURE["pnl_1d_ignore_transfers"]
# The fixture's last full day bucket: 2026-10-20 00:00 UTC.
OPEN_MS = PNL[-2]["timestamp"] * 1000
NOW_MS = PNL[-1]["timestamp"] * 1000

LIVE_ASSETS = [
    {"symbol": "USDC", "balance": "610.5", "index_price": "1", "usd": "610.5", "unrealized_pnl": ""},
    {"symbol": "ETH", "balance": "0.25", "index_price": "2437", "usd": "609.25", "unrealized_pnl": "12.5"},
]


class OpenTests(TestCase):
    def test_open_rounds_down_to_the_hour(self) -> None:
        now = 1_792_523_056_000
        self.assertEqual(day_open(now - 5 * HOUR_MS - 1234, now) % HOUR_MS, 0)
        self.assertEqual(day_open(now - 5 * HOUR_MS - 1234, now), now - now % HOUR_MS - 5 * HOUR_MS)
        self.assertEqual(day_open(None, now), now - now % DAY_MS)

    def test_open_out_of_range_is_refused(self) -> None:
        now = 1_792_523_056_000
        with self.assertRaises(OpenRefused):
            day_open(now + HOUR_MS, now)
        with self.assertRaises(OpenRefused):
            day_open(now - 31 * DAY_MS, now)


class KindTests(TestCase):
    def test_values_now_and_at_open(self) -> None:
        kinds = kinds_now(buckets(PNL), buckets(VALUES), OPEN_MS)
        self.assertEqual(kinds["perps"].value, D(str(VALUES[-1]["trade_pnl"])))
        self.assertEqual(kinds["perps"].value_at_open, D(str(VALUES[-2]["trade_pnl"])))
        self.assertEqual(kinds["staking"].value, D(str(VALUES[-1]["staking_pnl"])))
        # Before the first bucket the account did not exist: nothing at the open.
        early = kinds_now(buckets(PNL), buckets(VALUES), PNL[0]["timestamp"] * 1000 - DAY_MS)
        self.assertEqual(early["perps"].value_at_open, D("0"))

    def test_day_change_is_cumulative_pnl_now_less_at_open(self) -> None:
        kinds = kinds_now(buckets(PNL), buckets(VALUES), OPEN_MS)
        # The Journal's closed Round trips that day, scaled like the fixture.
        self.assertAlmostEqual(float(kinds["perps"].change), 13.97, delta=0.01)
        self.assertEqual(kinds["perps"].flows, D("0"))
        # An open on 10-18 takes in that day's LLP exit as a Flow, not a loss.
        since_18 = kinds_now(buckets(PNL), buckets(VALUES), PNL[-4]["timestamp"] * 1000)
        self.assertLess(since_18["llp"].flows, D("0"))
        self.assertGreater(since_18["perps"].flows, D("0"))

    def test_day_change_pct_counts_todays_flows_in_the_base(self) -> None:
        self.assertEqual(change_pct(D("10"), D("90"), D("10")), D("10"))
        self.assertIsNone(change_pct(D("5"), D("0"), D("0")))
        self.assertIsNone(change_pct(D("5"), D("10"), D("-10")))

    def test_a_drift_over_a_dollar_is_a_mismatch(self) -> None:
        self.assertEqual(mismatches(buckets(PNL), buckets(VALUES)), [])
        off = copy.deepcopy(VALUES)
        off[-2]["trade_pnl"] += 5
        found = mismatches(buckets(PNL), buckets(off))
        self.assertEqual([m.kind for m in found], ["perps"])
        self.assertAlmostEqual(float(found[0].drift), 5, delta=0.6)

    def test_the_partial_bucket_never_reads_as_a_mismatch(self) -> None:
        # Each request stamps its partial bucket "now"; LIT moved between the two.
        off = copy.deepcopy(VALUES)
        off[-1]["staking_pnl"] += 1.78
        off[-1]["timestamp"] += 1
        self.assertEqual(mismatches(buckets(PNL), buckets(off)), [])


class HoldingTests(TestCase):
    def test_staking_row_from_the_share_and_the_pool(self) -> None:
        share = FIXTURE["account"]["shares"][0]
        pool = FIXTURE["staking_pool_account"]
        row = pool_row(share, pool, D("3"))
        self.assertEqual(row.kind, "staking")
        self.assertEqual(row.pool, STAKING_POOL)
        self.assertEqual(row.unit, "LIT")
        lit = D(pool["assets"][0]["balance"])
        units = D(share["shares_amount"]) * lit / D(pool["pool_info"]["total_shares"])
        self.assertEqual(row.units, units)
        self.assertEqual(row.value, units * 3)
        self.assertGreater(row.units, D(share["principal_amount"]))

    def test_an_llp_share_is_valued_at_the_pools_share_price(self) -> None:
        share = {"public_pool_index": 281474976710654, "shares_amount": 1000, "principal_amount": "900"}
        pool = {"total_asset_value": "2000", "pool_info": {"total_shares": 2000, "annual_percentage_yield": 14.6}}
        row = pool_row(share, pool, D("3"))
        self.assertEqual((row.kind, row.unit, row.value), ("llp", "USD", D("1000")))

    def test_usdc_is_never_a_spot_row(self) -> None:
        rows = spot_rows(LIVE_ASSETS)
        self.assertEqual([r.symbol for r in rows], ["ETH"])
        self.assertEqual(rows[0].upnl, D("12.5"))

    def test_holding_detail_does_not_change_the_totals(self) -> None:
        bare = portfolio_now(
            now_ms=NOW_MS, open_ms=OPEN_MS, pnl_rows=PNL, value_rows=VALUES,
            account={}, pool_accounts={}, live_assets=[], lit_price=D("0"),
        )
        full = portfolio_now(
            now_ms=NOW_MS, open_ms=OPEN_MS, pnl_rows=PNL, value_rows=VALUES,
            account=FIXTURE["account"], pool_accounts={STAKING_POOL: FIXTURE["staking_pool_account"]},
            live_assets=LIVE_ASSETS, lit_price=D("3"),
        )
        self.assertEqual(bare.to_json()["total"], full.to_json()["total"])
        self.assertEqual(len(full.to_json()["pools"]), 1)


def _raw() -> dict[str, object]:
    return {
        "pnl": PNL,
        "values": VALUES,
        "account": FIXTURE["account"],
        "pools": {STAKING_POOL: FIXTURE["staking_pool_account"]},
    }


class ReadTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        portfolio_venue.clear_cache()
        self.addCleanup(portfolio_venue.clear_cache)

    async def test_the_answer_is_reused_for_30s(self) -> None:
        clock = [1000.0]
        with (
            patch.object(portfolio_venue, "read_venue", AsyncMock(return_value=_raw())) as read,
            patch.object(portfolio_venue.time, "monotonic", lambda: clock[0]),
        ):
            await portfolio_venue.read_portfolio(OPEN_MS, now_ms=NOW_MS)
            clock[0] += 29
            await portfolio_venue.read_portfolio(OPEN_MS, now_ms=NOW_MS)
            self.assertEqual(read.await_count, 1)
            await portfolio_venue.read_portfolio(OPEN_MS - HOUR_MS, now_ms=NOW_MS)
            self.assertEqual(read.await_count, 2, "another Day open is its own answer")
            clock[0] += 2
            await portfolio_venue.read_portfolio(OPEN_MS, now_ms=NOW_MS)
            self.assertEqual(read.await_count, 3)

    async def test_a_plain_answer_reads_only_the_pnl_series(self) -> None:
        reads: list[str] = []

        async def get(_client: object, _auth: str, path: str, params: dict[str, object]) -> dict[str, object]:
            reads.append(f"{path}{'+values' if params.get('ignore_transfers') else ''}")
            if path == "/api/v1/pnl":
                return {"pnl": VALUES if params.get("ignore_transfers") else PNL}
            return {"accounts": [FIXTURE["account"]]}

        with (
            patch.object(settings, "lighter_account_index", 1001),
            patch.object(portfolio_venue, "_get", get),
            patch("mayedge.lighter.orders.order_service.auth_token", AsyncMock(return_value="t")),
        ):
            plain = await portfolio_venue.read_portfolio(OPEN_MS, now_ms=NOW_MS, detail=False)
            self.assertEqual(reads, ["/api/v1/pnl", "/api/v1/pnl+values"])
            self.assertEqual(plain.pools, [])
            detailed = await portfolio_venue.read_portfolio(OPEN_MS, now_ms=NOW_MS)
            # Both pnl series again, then the account and the one pool held.
            self.assertEqual(reads[2:], ["/api/v1/pnl", "/api/v1/pnl+values", "/api/v1/account", "/api/v1/account"])
            self.assertEqual(len(detailed.pools), 1)
            again = await portfolio_venue.read_portfolio(OPEN_MS, now_ms=NOW_MS, detail=False)
            self.assertIs(again, detailed, "a detailed answer serves a plain one")
            self.assertEqual(len(reads), 6)

    async def test_the_route_answers_the_totals_and_refuses_a_future_open(self) -> None:
        with (
            patch.object(settings, "lighter_api_private_key", "k"),
            patch.object(settings, "lighter_account_index", 1001),
            patch.object(portfolio_venue, "read_venue", AsyncMock(return_value=_raw())),
        ):
            app = create_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as client:
                ok = await client.get("/api/portfolio")
                self.assertEqual(ok.status_code, 200)
                body = ok.json()
                self.assertEqual(set(body["kinds"]), {"perps", "spot", "llp", "staking"})
                self.assertEqual(body["mismatch"], [])
                self.assertIn("change_pct", body["total"])
                future = await client.get("/api/portfolio", params={"open": 10**13})
                self.assertEqual(future.status_code, 400)
