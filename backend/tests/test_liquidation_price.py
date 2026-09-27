from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock, patch

from mayedge.lighter.account import AccountService
from mayedge.lighter.equity import format_cross_liquidation_price, liquidation_threshold_usd
from mayedge.lighter.gateway import LighterGateway
from mayedge.lighter.models import MarketMeta, Position


def _position(**overrides: object) -> Position:
    fields: dict[str, object] = {
        "market_index": 120,
        "symbol": "LIT",
        "size": "100",
        "entry_price": "10",
        "mark_price": "10",
        "unrealized_pnl": "0",
        "leverage": 5,
        "margin_mode": "cross",
        "liquidation_price": "10",
        "side": "long",
    }
    fields.update(overrides)
    return Position(**fields)  # type: ignore[arg-type]


def _market(index: int, mark: float, maintenance: int = 1200) -> MarketMeta:
    meta = MarketMeta(index, "LIT", 4, 2, 1.0, 10.0, market_type="perp")
    meta.mark_price = mark
    meta.maintenance_margin_fraction = maintenance
    return meta


def _emit(svc: AccountService, markets: dict[int, MarketMeta]) -> dict:
    gw = MagicMock()
    gw.get_market.return_value = None
    gw.get_market_by_index.side_effect = lambda index: markets.get(index)
    captured: list[dict] = []
    gw.broadcast.side_effect = captured.append
    with patch("mayedge.lighter.account.gateway", gw):
        svc._emit_account()
    account = [row for row in captured if row.get("type") == "account"][-1]
    return {int(p["market_index"]): p for p in account["positions"]}


_ETH = {"index_price": 100.0, "loan_to_value": 0.7, "liquidation_threshold": 0.85}


class LiquidationThresholdTests(TestCase):
    def test_quote_margin_is_not_added(self) -> None:
        assets = [
            {"symbol": "USDC", "margin_balance": "10000"},
            {"symbol": "ETH", "margin_balance": "1"},
        ]
        self.assertAlmostEqual(liquidation_threshold_usd(assets, {"ETH": _ETH}), 85.0)

    def test_ltv_is_not_the_haircut(self) -> None:
        assets = [{"symbol": "ETH", "margin_balance": "1"}]
        self.assertAlmostEqual(liquidation_threshold_usd(assets, {"ETH": _ETH}), 85.0)
        self.assertNotAlmostEqual(liquidation_threshold_usd(assets, {"ETH": _ETH}), 70.0)


class CrossLiquidationPriceTests(TestCase):
    def setUp(self) -> None:
        self.svc = AccountService()
        self.svc._summary.cross_portfolio_value = "50"
        self.svc._assets = [
            {"symbol": "ETH", "margin_balance": "1"},
            {"symbol": "USDC", "margin_balance": "10000"},
        ]
        self.svc._asset_meta = {"ETH": dict(_ETH)}

    def test_eth_margin_moves_the_price_below_the_venue_mark(self) -> None:
        self.svc._summary.positions = [_position()]
        by_mi = _emit(self.svc, {120: _market(120, 10.0)})
        # TALT 135, MMR 120, long 100 @ 10, maintenance 12%.
        self.assertAlmostEqual(float(by_mi[120]["liquidation_price"]), 10 - 15 / 88, places=6)

    def test_ltv_would_leave_the_price_on_the_mark(self) -> None:
        self.svc._summary.positions = [_position()]
        by_mi = _emit(self.svc, {120: _market(120, 10.0)})
        self.assertNotAlmostEqual(float(by_mi[120]["liquidation_price"]), 10.0)

    def test_quote_margin_is_not_double_counted(self) -> None:
        self.svc._summary.positions = [_position()]
        with_quote = _emit(self.svc, {120: _market(120, 10.0)})
        self.svc._assets = [{"symbol": "ETH", "margin_balance": "1"}]
        self.svc._summary.positions = [_position()]
        without_quote = _emit(self.svc, {120: _market(120, 10.0)})
        self.assertEqual(
            with_quote[120]["liquidation_price"],
            without_quote[120]["liquidation_price"],
        )

    def test_isolated_keeps_the_venue_field(self) -> None:
        self.svc._summary.positions = [
            _position(),
            _position(
                market_index=1,
                symbol="ETH",
                margin_mode="isolated",
                liquidation_price="1.5",
                size="2",
                side="short",
            ),
        ]
        by_mi = _emit(
            self.svc,
            {120: _market(120, 10.0), 1: _market(1, 100.0)},
        )
        self.assertAlmostEqual(float(by_mi[120]["liquidation_price"]), 10 - 15 / 88, places=6)
        self.assertEqual(by_mi[1]["liquidation_price"], "1.5")

    def test_no_non_quote_margin_keeps_the_venue_field(self) -> None:
        self.svc._assets = [{"symbol": "USDC", "margin_balance": "10000"}]
        self.svc._summary.positions = [_position(liquidation_price="4.25")]
        by_mi = _emit(self.svc, {120: _market(120, 10.0)})
        self.assertEqual(by_mi[120]["liquidation_price"], "4.25")

    def test_price_is_not_clamped_to_the_mark_when_already_through_maintenance(self) -> None:
        self.svc._summary.positions = [
            _position(),
            _position(market_index=2, symbol="SOL", size="10", mark_price="20"),
        ]
        by_mi = _emit(
            self.svc,
            {120: _market(120, 10.0), 2: _market(2, 20.0)},
        )
        # Second position adds maintenance, so the long's price sits above the mark.
        self.assertAlmostEqual(float(by_mi[120]["liquidation_price"]), 10 + 9 / 88, places=6)

    def test_unknown_maintenance_keeps_the_venue_field(self) -> None:
        self.svc._summary.positions = [_position(liquidation_price="4.25")]
        by_mi = _emit(self.svc, {120: _market(120, 10.0, maintenance=0)})
        self.assertEqual(by_mi[120]["liquidation_price"], "4.25")

    def test_non_positive_price_is_blank(self) -> None:
        price = format_cross_liquidation_price(
            mark=10,
            size=1,
            maintenance_fraction=0.1,
            talt=900,
            mmr=10,
        )
        self.assertEqual(price, "0")


class AssetMetaTests(IsolatedAsyncioTestCase):
    async def test_asset_details_keep_liquidation_threshold(self) -> None:
        asset = SimpleNamespace(
            symbol="ETH",
            index_price="100",
            loan_to_value="0.7",
            liquidation_threshold="0.85",
        )
        order_api = MagicMock()
        order_api.asset_details = AsyncMock(return_value=SimpleNamespace(asset_details=[asset]))
        svc = AccountService()
        with (
            patch("mayedge.lighter.account.gateway") as gw,
            patch("mayedge.lighter.account.lighter.OrderApi", return_value=order_api),
        ):
            gw.client = object()
            await svc._load_asset_meta(force=True)
        self.assertEqual(svc._asset_meta["ETH"]["liquidation_threshold"], 0.85)
        self.assertEqual(svc._asset_meta["ETH"]["loan_to_value"], 0.7)

    async def test_order_book_details_store_maintenance_fraction(self) -> None:
        book = SimpleNamespace(
            symbol="LIT",
            market_id=120,
            supported_price_decimals=4,
            supported_size_decimals=2,
            min_base_amount="1",
            min_quote_amount="10",
            market_type="perp",
        )
        detail = SimpleNamespace(
            market_id=120,
            last_trade_price=4.7,
            mark_price=4.7,
            market_config=None,
            daily_quote_token_volume=0,
            open_interest=None,
            daily_price_change=None,
            min_initial_margin_fraction=2000,
            default_initial_margin_fraction=2000,
            maintenance_margin_fraction=1200,
        )
        order_api = MagicMock()
        order_api.order_books = AsyncMock(return_value=SimpleNamespace(order_books=[book]))
        order_api.order_book_details = AsyncMock(
            return_value=SimpleNamespace(order_book_details=[detail])
        )
        gw = LighterGateway()
        gw._client = cast(Any, object())
        with patch("mayedge.lighter.gateway.lighter.OrderApi", return_value=order_api):
            await gw._load_markets()
        self.assertEqual(gw._markets[120].maintenance_margin_fraction, 1200)
