from __future__ import annotations

from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock, patch

from mayedge.lighter.account import AccountService
from mayedge.lighter.equity import portfolio_margin_usd, trade_available_usd
from mayedge.lighter.models import AccountSummary
from mayedge.lighter.parse import merge_account_assets, public_assets


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

    def test_trade_available_adds_asset_ltv_to_usdc_free(self) -> None:
        # 975.61 USDC free + 1 ETH × 2464.57 × 0.7 LTV
        self.assertAlmostEqual(
            trade_available_usd(975.61, 2716.81, 991.611),
            2700.81,
            places=2,
        )

    def test_trade_available_matches_usdc_when_no_assets(self) -> None:
        self.assertAlmostEqual(trade_available_usd(975.61, 991.611, 991.611), 975.61, places=2)


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
        self.assertAlmostEqual(float(acc["trade_available"]), 2700.81, places=2)
        self.assertNotIn("trading_equity", acc)
        self.assertNotIn("spot_equity", acc)
        self.assertAlmostEqual(float(acc["portfolio_margin"]), 2716.81, places=2)

    def test_user_stats_trade_available_stays_usdc_without_assets(self) -> None:
        svc = AccountService()
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
        self.assertAlmostEqual(float(acc["portfolio_margin"]), 991.611, places=3)


class PublicAssetsTests(TestCase):
    def test_usdc_uses_quote_index_and_full_ltv(self) -> None:
        rows = public_assets(
            [
                {
                    "symbol": "USDC",
                    "balance": "1362.84",
                    "margin_balance": "16.74",
                    "locked_balance": "0",
                }
            ],
            {},
        )
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.symbol, "USDC")
        self.assertEqual(row.balance, "1379.58")
        self.assertEqual(row.margin_balance, "16.74")
        self.assertAlmostEqual(float(row.index_price), 1.0)
        self.assertAlmostEqual(float(row.ltv), 1.0)
        self.assertAlmostEqual(float(row.usd), 1379.58)
        self.assertAlmostEqual(float(row.available), 1379.58)

    def test_available_prefers_venue_field(self) -> None:
        rows = public_assets(
            [
                {
                    "symbol": "USDC",
                    "balance": "1362.84",
                    "margin_balance": "16.74",
                    "locked_balance": "0",
                    "available_balance": "16.74",
                }
            ],
            {},
        )
        self.assertEqual(rows[0].available, "16.74")

    def test_eth_usd_is_balance_times_index(self) -> None:
        rows = public_assets(
            [{"symbol": "ETH", "balance": "1.0", "margin_balance": "0"}],
            {"ETH": {"index_price": 2464.57, "loan_to_value": 0.7}},
        )
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.symbol, "ETH")
        self.assertAlmostEqual(float(row.usd), 2464.57)
        self.assertAlmostEqual(float(row.ltv), 0.7)
        self.assertAlmostEqual(float(row.index_price), 2464.57)
        self.assertEqual(row.unrealized_pnl, "")

    def test_spot_upnl_is_index_minus_avg_entry_times_size(self) -> None:
        """Lighter blotter: (index − avg_entry) × total size; quote has none."""
        rows = public_assets(
            [
                {"symbol": "ETH", "asset_id": 1, "balance": "1.0", "margin_balance": "0"},
                {"symbol": "USDC", "asset_id": 3, "balance": "100"},
            ],
            {"ETH": {"index_price": 2464.57, "loan_to_value": 0.7}},
            {1: "1850.45"},
        )
        self.assertEqual(len(rows), 2)
        eth, usdc = rows
        self.assertAlmostEqual(float(eth.unrealized_pnl), 614.12)
        self.assertEqual(usdc.unrealized_pnl, "")

    def test_zero_balance_is_omitted(self) -> None:
        rows = public_assets(
            [
                {"symbol": "ETH", "balance": "0"},
                {"symbol": "USDC", "balance": "10"},
            ],
            {},
        )
        self.assertEqual([r.symbol for r in rows], ["USDC"])

    def test_margin_only_holding_is_kept(self) -> None:
        """Perp collateral can sit in margin_balance with a zero spot balance."""
        rows = public_assets(
            [
                {"symbol": "ETH", "balance": "0", "margin_balance": "1.0"},
                {"symbol": "USDC", "balance": "10"},
            ],
            {"ETH": {"index_price": 2464.57, "loan_to_value": 0.7}},
        )
        self.assertEqual([r.symbol for r in rows], ["ETH", "USDC"])
        eth = rows[0]
        self.assertAlmostEqual(float(eth.balance), 1.0)
        self.assertEqual(eth.margin_balance, "1.0")
        self.assertAlmostEqual(float(eth.available), 1.0)
        self.assertAlmostEqual(float(eth.usd), 2464.57)
        self.assertAlmostEqual(float(eth.ltv), 0.7)

    def test_spot_plus_margin_is_total_owned(self) -> None:
        rows = public_assets(
            [
                {
                    "symbol": "ETH",
                    "balance": "10",
                    "margin_balance": "40",
                    "locked_balance": "0",
                }
            ],
            {"ETH": {"index_price": 100.0, "loan_to_value": 0.7}},
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].balance, "50")
        self.assertEqual(rows[0].available, "50")
        self.assertEqual(rows[0].margin_balance, "40")
        self.assertAlmostEqual(float(rows[0].usd), 5000.0)

    def test_available_subtracts_spot_lock_from_total(self) -> None:
        rows = public_assets(
            [
                {
                    "symbol": "ETH",
                    "balance": "10",
                    "margin_balance": "40",
                    "locked_balance": "2",
                }
            ],
            {"ETH": {"index_price": 100.0, "loan_to_value": 0.7}},
        )
        self.assertEqual(rows[0].available, "48")

    def test_dust_usd_is_omitted(self) -> None:
        rows = public_assets(
            [{"symbol": "LIT", "balance": "0.000009", "margin_balance": "0"}],
            {"LIT": {"index_price": 5.1135, "loan_to_value": 0}},
        )
        self.assertEqual(rows, [])


class AccountAssetsWireTests(TestCase):
    def test_account_payload_includes_public_assets(self) -> None:
        summary = AccountSummary(
            collateral="0",
            available="0",
            unrealized_pnl="0",
            assets=public_assets(
                [{"symbol": "USDC", "balance": "1362.84", "margin_balance": "16.74"}],
                {},
            ),
        )
        payload = summary.to_public_dict()
        self.assertNotIn("trading_equity", payload)
        self.assertNotIn("spot_equity", payload)
        row = payload["assets"][0]
        self.assertEqual(row["symbol"], "USDC")
        self.assertEqual(row["balance"], "1379.58")
        self.assertAlmostEqual(float(row["usd"]), 1379.58)
        self.assertAlmostEqual(float(row["index_price"]), 1.0)
        self.assertAlmostEqual(float(row["ltv"]), 1.0)

    def test_user_stats_publish_projects_cached_assets(self) -> None:
        svc = AccountService()
        svc._assets = [{"symbol": "ETH", "balance": "0", "margin_balance": "1.0"}]
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
        self.assertEqual(acc["assets"][0]["symbol"], "ETH")
        self.assertAlmostEqual(float(acc["assets"][0]["usd"]), 2464.57)
        self.assertAlmostEqual(float(acc["assets"][0]["ltv"]), 0.7)

    def test_ws_assets_dict_publishes_every_holding(self) -> None:
        svc = AccountService()
        svc._asset_meta = {"ETH": {"index_price": 2464.57, "loan_to_value": 0.7}}
        gw = MagicMock()
        gw.get_market_by_index.return_value = None
        gw.get_market.return_value = None
        captured: list[dict] = []
        gw.broadcast.side_effect = captured.append
        with patch("mayedge.lighter.account.gateway", gw):
            svc.handle_account_ws(
                {
                    "type": "subscribed/account_all_assets",
                    "assets": {
                        "1": {
                            "symbol": "ETH",
                            "asset_id": 1,
                            "balance": "7.1072",
                            "locked_balance": "0.0000",
                        },
                        "3": {
                            "symbol": "USDC",
                            "asset_id": 3,
                            "balance": "6343.581906",
                            "locked_balance": "297.000000",
                        },
                    },
                }
            )
        acc = [m for m in captured if m.get("type") == "account"][-1]
        self.assertEqual({row["symbol"] for row in acc["assets"]}, {"ETH", "USDC"})

    def test_ws_avg_entry_publishes_asset_upnl(self) -> None:
        svc = AccountService()
        svc._asset_meta = {"ETH": {"index_price": 2464.57, "loan_to_value": 0.7}}
        gw = MagicMock()
        gw.get_market_by_index.return_value = None
        gw.get_market.return_value = None
        captured: list[dict] = []
        gw.broadcast.side_effect = captured.append
        with patch("mayedge.lighter.account.gateway", gw):
            svc.handle_account_ws(
                {
                    "type": "subscribed/account_all_assets",
                    "assets": {
                        "1": {
                            "symbol": "ETH",
                            "asset_id": 1,
                            "balance": "1.0",
                            "locked_balance": "0",
                        },
                        "3": {
                            "symbol": "USDC",
                            "asset_id": 3,
                            "balance": "100",
                            "locked_balance": "0",
                        },
                    },
                }
            )
            svc.handle_account_ws(
                {
                    "type": "subscribed/account_spot_avg_entry_prices",
                    "avg_entry_prices": {
                        "1": {
                            "asset_id": 1,
                            "avg_entry_price": "1850.45",
                            "asset_size": "1.0",
                        }
                    },
                }
            )
        acc = [m for m in captured if m.get("type") == "account"][-1]
        by_sym = {row["symbol"]: row for row in acc["assets"]}
        self.assertAlmostEqual(float(by_sym["ETH"]["unrealized_pnl"]), 614.12)
        self.assertEqual(by_sym["USDC"]["unrealized_pnl"], "")


class AccountAssetsRestTests(IsolatedAsyncioTestCase):
    async def test_rest_hydrate_asks_for_full_account_assets(self) -> None:
        """SDK default is active_only=False so assets[] is every holding, not active markets only."""
        svc = AccountService()
        usdc = MagicMock(
            symbol="USDC",
            asset_id=3,
            balance="100",
            locked_balance="0",
            margin_balance="10",
            margin_mode="enabled",
        )
        eth = MagicMock(
            symbol="ETH",
            asset_id=1,
            balance="2",
            locked_balance="0",
            margin_balance="2",
            margin_mode="enabled",
        )
        account = MagicMock()
        account.positions = []
        account.assets = [usdc, eth]
        account.available_balance = "90"
        account.collateral = "100"
        account.total_asset_value = "100"
        account.cross_asset_value = "100"
        resp = MagicMock()
        resp.accounts = [account]
        api = MagicMock()
        api.account = AsyncMock(return_value=resp)
        with (
            patch("mayedge.lighter.account.settings") as settings,
            patch("mayedge.lighter.account.lighter.AccountApi", return_value=api),
            patch("mayedge.lighter.account.gateway") as gw,
        ):
            settings.lighter_account_index = 1
            gw.get_market.return_value = None
            gw.get_market_by_index.return_value = None
            summary = await svc.fetch_account_summary()
        self.assertIn("active_only", api.account.call_args.kwargs)
        self.assertFalse(api.account.call_args.kwargs["active_only"])
        self.assertEqual({a.symbol for a in summary.assets}, {"USDC", "ETH"})


class TouchMarksAssetsTests(TestCase):
    def test_touch_marks_republishes_when_holdings_exist(self) -> None:
        svc = AccountService()
        svc._assets = [{"symbol": "ETH", "balance": "0", "margin_balance": "1.0"}]
        svc._asset_meta = {"ETH": {"index_price": 2000.0, "loan_to_value": 0.7}}
        gw = MagicMock()
        gw.get_market_by_index.return_value = None
        mkt = MagicMock()
        mkt.index_price = 2464.57
        gw.get_market.return_value = mkt
        captured: list[dict] = []
        gw.broadcast.side_effect = captured.append
        with patch("mayedge.lighter.account.gateway", gw):
            svc.touch_marks()
        acc = [m for m in captured if m.get("type") == "account"]
        self.assertEqual(len(acc), 1)
        self.assertAlmostEqual(float(acc[0]["assets"][0]["index_price"]), 2464.57)
        self.assertAlmostEqual(float(acc[0]["assets"][0]["usd"]), 2464.57)

    def test_touch_marks_stays_quiet_without_positions_or_holdings(self) -> None:
        svc = AccountService()
        gw = MagicMock()
        captured: list[dict] = []
        gw.broadcast.side_effect = captured.append
        with patch("mayedge.lighter.account.gateway", gw):
            svc.touch_marks()
        self.assertEqual(captured, [])
