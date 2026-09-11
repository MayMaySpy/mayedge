from __future__ import annotations

from unittest import TestCase
from unittest.mock import MagicMock, patch

from mayedge.lighter.account import AccountService
from mayedge.lighter.equity import portfolio_margin_usd
from mayedge.lighter.parse import merge_account_assets


class MergeAssetsTests(TestCase):
    def test_ws_balance_update_keeps_rest_margin_fields(self) -> None:
        rest = [
            {
                "symbol": "ETH",
                "balance": "2",
                "margin_balance": "2",
                "margin_mode": "enabled",
            }
        ]
        ws = {"1": {"symbol": "ETH", "asset_id": 1, "balance": "2.1", "locked_balance": "0"}}
        merged = {r["symbol"]: r for r in merge_account_assets(rest, ws)}
        self.assertEqual(merged["ETH"]["balance"], "2.1")
        self.assertEqual(merged["ETH"]["margin_balance"], "2")
        self.assertEqual(merged["ETH"]["margin_mode"], "enabled")


class PortfolioMarginTests(TestCase):
    def test_tav_adds_ltv_haircut_on_non_quote_margin(self) -> None:
        assets = [
            {"symbol": "USDC", "margin_balance": "992.35"},
            {"symbol": "ETH", "margin_balance": "1.0"},
        ]
        details = {"ETH": {"index_price": 2464.57, "loan_to_value": 0.7}}
        self.assertAlmostEqual(
            portfolio_margin_usd(991.611, assets, details),
            2716.81,
            places=2,
        )


class AccountStatsWireTests(TestCase):
    def test_user_stats_available_and_margin(self) -> None:
        svc = AccountService()
        svc._assets = [{"symbol": "ETH", "margin_balance": "1.0"}]
        svc._asset_meta = {"ETH": {"index_price": 2464.57, "loan_to_value": 0.7}}
        gw = MagicMock()
        gw.get_market_by_index.return_value = None
        gw.get_market.return_value = None
        captured: list[dict] = []
        gw.broadcast.side_effect = captured.append
        with patch("mayedge.lighter.account.gateway", gw):
            svc.handle_account_ws(
                {
                    "type": "update/user_stats",
                    "stats": {
                        "collateral": "1050.76",
                        "portfolio_value": "1048.04",
                        "available_balance": "975.61",
                        "cross_stats": {"portfolio_value": "991.611"},
                    },
                }
            )
        acc = [m for m in captured if m.get("type") == "account"][-1]
        self.assertEqual(acc["available"], "975.61")
        self.assertEqual(acc["trade_available"], "975.61")
        self.assertNotIn("trading_equity", acc)
        self.assertNotIn("spot_equity", acc)
        self.assertAlmostEqual(float(acc["portfolio_margin"]), 2716.81, places=2)
