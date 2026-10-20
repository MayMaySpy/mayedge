"""What the venue says about the Portfolio (docs/portfolio-rules.md), pinned on a real answer.

The fixture is mainnet's shape on 2026-10-20 with the account's own figures scaled.
If the venue changes what a field means, this fails before a number on the page is wrong.
"""

from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path
from unittest import TestCase

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "portfolio_raw.json").read_text())
LLP_INDEX = 281474976710654
STAKING_INDEX = 281474976624800

# Holding kind → (value and PnL field, inflow field, outflow field) in a pnl bucket.
KINDS = {
    "perps": ("trade_pnl", "inflow", "outflow"),
    "spot": ("trade_spot_pnl", "spot_inflow", "spot_outflow"),
    "llp": ("pool_pnl", "pool_inflow", "pool_outflow"),
    "staking": ("staking_pnl", "staking_inflow", "staking_outflow"),
}


class PnlBucketTests(TestCase):
    def test_value_less_cumulative_pnl_is_the_net_flow_of_each_kind(self) -> None:
        # ignore_transfers=true answers each kind's value; the default answers PnL since the account opened.
        for value_row, pnl_row in zip(FIXTURE["pnl_1d_ignore_transfers"], FIXTURE["pnl_1d"], strict=True):
            self.assertEqual(value_row["timestamp"], pnl_row["timestamp"])
            for kind, (field, inflow, outflow) in KINDS.items():
                flows = pnl_row[inflow] - pnl_row[outflow]
                self.assertAlmostEqual(value_row[field] - pnl_row[field], flows, delta=1.0, msg=kind)

    def test_pnl_and_flows_are_cumulative_and_only_volume_is_per_bucket(self) -> None:
        rows = FIXTURE["pnl_1h"]
        for before, after in pairwise(rows):
            self.assertGreaterEqual(after["inflow"], before["inflow"])
            self.assertGreaterEqual(after["outflow"], before["outflow"])
        # A day's change is the cumulative PnL now less the bucket at the day's open.
        day = FIXTURE["pnl_1d"]
        today = day[-1]["trade_pnl"] - day[-2]["trade_pnl"]
        self.assertAlmostEqual(today, 13.97, delta=0.01)

    def test_bucket_times_are_seconds_and_the_last_bucket_is_now(self) -> None:
        for key in ("pnl_1d", "pnl_1h", "pnl_1d_ignore_transfers"):
            stamps = [row["timestamp"] for row in FIXTURE[key]]
            self.assertTrue(all(ts < 10**12 for ts in stamps), key)
            self.assertNotEqual(stamps[-1] % 3600, 0, f"{key}: the last bucket is the partial one, stamped now")
            self.assertTrue(all(ts % 3600 == 0 for ts in stamps[:-1]), key)

    def test_staked_lit_is_not_a_bucket_field(self) -> None:
        # The SDK model has staked_lit; the live answer does not. Value staking from the pool instead.
        self.assertNotIn("staked_lit", FIXTURE["pnl_1d"][-1])


class AccountTests(TestCase):
    def test_usdc_collateral_is_perps_and_never_spot(self) -> None:
        account = FIXTURE["account"]
        usdc = next(a for a in account["assets"] if a["symbol"] == "USDC")
        self.assertEqual(float(usdc["balance"]), 0.0)
        self.assertAlmostEqual(float(usdc["margin_balance"]), float(account["total_asset_value"]), delta=0.01)
        # total_asset_value is the perps kind's value; the venue's own perps value agrees.
        self.assertAlmostEqual(
            FIXTURE["pnl_1d_ignore_transfers"][-1]["trade_pnl"], float(account["total_asset_value"]), delta=1.0
        )

    def test_spot_used_as_collateral_sits_in_margin_balance_and_counts_as_spot(self) -> None:
        account = FIXTURE["account"]
        eth = next(a for a in account["assets"] if a["symbol"] == "ETH")
        self.assertEqual(float(eth["balance"]), 0.0)
        self.assertGreater(float(eth["margin_balance"]), 0.0)
        # cross_asset_value adds it with a haircut, total_asset_value leaves it out.
        self.assertGreater(float(account["cross_asset_value"]), float(account["total_asset_value"]))
        self.assertGreater(FIXTURE["pnl_1d_ignore_transfers"][-1]["trade_spot_pnl"], 0.0)

    def test_the_share_is_lit_staking_and_principal_is_in_lit(self) -> None:
        share = FIXTURE["account"]["shares"][0]
        self.assertEqual(share["public_pool_index"], STAKING_INDEX)
        self.assertEqual(share["entry_timestamp"], 0, "entry_timestamp is not set: do not show it as a date")
        pool = FIXTURE["staking_pool_account"]
        lit = float(next(a["balance"] for a in pool["assets"] if a["symbol"] == "LIT"))
        staked_lit = share["shares_amount"] * lit / pool["pool_info"]["total_shares"]
        # Staking yield grows the LIT behind each share past what was put in.
        self.assertGreater(staked_lit, float(share["principal_amount"]))
        self.assertLess(staked_lit, float(share["principal_amount"]) * 1.1)


class PoolTests(TestCase):
    def test_llp_and_staking_are_found_by_listing_down_from_the_top_index(self) -> None:
        llp = FIXTURE["pools_listing_top"][0]
        self.assertEqual(llp["account_index"], LLP_INDEX)
        self.assertEqual(llp["account_type"], 3)
        self.assertTrue(llp["name"].startswith("Lighter Liquidity Provider"))
        stake = FIXTURE["pools_listing_stake"][0]
        self.assertEqual(stake["account_index"], STAKING_INDEX)
        self.assertEqual(stake["account_type"], 4)
        # The staking pool's value is LIT, so its USD total_asset_value is 0 and its spot value carries it.
        self.assertEqual(float(stake["total_asset_value"]), 0.0)
        self.assertGreater(float(stake["total_spot_value"]), 0.0)

    def test_a_share_price_is_usd_per_share(self) -> None:
        prices = FIXTURE["staking_pool_account"]["pool_info"]["share_prices"]
        self.assertTrue(all(row["timestamp"] < 10**12 for row in prices))
        returns = FIXTURE["staking_pool_account"]["pool_info"]["daily_returns"]
        # The daily return is the share price's own move: price[i] / price[i-1] - 1.
        last, before = prices[-1]["share_price"], prices[-2]["share_price"]
        self.assertAlmostEqual(returns[-1]["daily_return"], last / before - 1, delta=0.005)
