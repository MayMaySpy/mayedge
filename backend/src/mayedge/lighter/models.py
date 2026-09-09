from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal
from typing import Any

from mayedge.numbers import fmt_decimal


def normalize_market_type(raw: Any) -> str:
    """Map Lighter market_type strings / enums to ``perp`` or ``spot``."""
    text = str(raw or "perp").strip().lower()
    if "spot" in text:
        return "spot"
    return "perp"


@dataclass
class MarketMeta:
    market_index: int
    symbol: str
    price_decimals: int
    size_decimals: int
    min_base_amount: float
    min_quote_amount: float
    market_type: str = "perp"
    mark_price: float | None = None
    index_price: float | None = None
    funding_rate: float | None = None
    last_trade_price: float | None = None
    min_initial_margin_fraction: int = 500
    default_initial_margin_fraction: int = 500
    volume_24h: float = 0.0
    volume_base_24h: float = 0.0
    change_24h: float | None = None
    open_interest: float | None = None
    open_interest_limit: float | None = None
    best_bid_price: float | None = None
    best_ask_price: float | None = None
    mid_price: float | None = None
    premium: float | None = None
    funding_timestamp: int | None = None
    daily_price_high: float | None = None
    daily_price_low: float | None = None

    @property
    def is_perp(self) -> bool:
        return normalize_market_type(self.market_type) != "spot"

    @property
    def max_leverage(self) -> int:
        """Highest integer leverage this market allows (from min IMF)."""
        return margin_fraction_to_leverage(self.min_initial_margin_fraction, 20)

    @property
    def default_leverage(self) -> int:
        allowed = self.allowed_leverages
        lev = margin_fraction_to_leverage(self.default_initial_margin_fraction, self.max_leverage)
        if allowed:
            return min(allowed, key=lambda x: abs(x - lev))
        return min(max(1, lev), self.max_leverage)

    @property
    def allowed_leverages(self) -> list[int]:
        return canonical_leverages(self.min_initial_margin_fraction)

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "market_index": self.market_index,
            "symbol": self.symbol,
            "market_type": normalize_market_type(self.market_type),
            "is_perp": self.is_perp,
            "price_decimals": self.price_decimals,
            "size_decimals": self.size_decimals,
            "min_base_amount": self.min_base_amount,
            "min_quote_amount": self.min_quote_amount,
            "mark_price": self.mark_price,
            "index_price": self.index_price,
            "last_trade_price": self.last_trade_price,
            "max_leverage": self.max_leverage,
            "default_leverage": self.default_leverage,
            "allowed_leverages": self.allowed_leverages,
            "volume_24h": self.volume_24h,
            "volume_base_24h": self.volume_base_24h,
            "change_24h": self.change_24h,
            "funding_rate": self.funding_rate,
            "funding_apr": None if self.funding_rate is None else self.funding_rate * 24 * 365,
            "open_interest": self.open_interest,
            "open_interest_limit": self.open_interest_limit,
            "best_bid_price": self.best_bid_price,
            "best_ask_price": self.best_ask_price,
            "mid_price": self.mid_price,
            "premium": self.premium,
            "funding_timestamp": self.funding_timestamp,
            "daily_price_high": self.daily_price_high,
            "daily_price_low": self.daily_price_low,
        }

    def as_quote_dict(self) -> dict[str, Any]:
        return {
            "market_index": self.market_index,
            "symbol": self.symbol,
            "mark_price": self.mark_price,
            "index_price": self.index_price,
            "last_trade_price": self.last_trade_price,
            "change_24h": self.change_24h,
            "open_interest": self.open_interest,
            "funding_rate": self.funding_rate,
            "funding_apr": None if self.funding_rate is None else self.funding_rate * 24 * 365,
            "volume_24h": self.volume_24h,
            "best_bid_price": self.best_bid_price,
            "best_ask_price": self.best_ask_price,
            "mid_price": self.mid_price,
        }

    def quote_key(self) -> tuple[Any, ...]:
        return (
            self.mark_price,
            self.last_trade_price,
            self.index_price,
            self.open_interest,
            self.funding_rate,
            self.change_24h,
            self.volume_24h,
            self.best_bid_price,
            self.best_ask_price,
            self.mid_price,
        )


@dataclass
class OrderBookLevel:
    price: str
    size: str


@dataclass
class OrderBookSnapshot:
    market_index: int
    bids: list[OrderBookLevel] = field(default_factory=list)
    asks: list[OrderBookLevel] = field(default_factory=list)
    timestamp: int | None = None


@dataclass
class Trade:
    price: str
    size: str
    side: str
    timestamp: int


@dataclass
class Candle:
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Position:
    market_index: int
    symbol: str
    size: str
    entry_price: str
    mark_price: str
    unrealized_pnl: str
    leverage: int
    margin_mode: str
    liquidation_price: str = ""
    funding_paid: str = "0"
    allocated_margin: str = "0"
    side: str = "long"


@dataclass
class OpenOrder:
    order_index: int
    client_order_index: int
    market_index: int
    symbol: str
    side: str
    price: str
    size: str
    remaining: str
    order_type: str
    reduce_only: bool
    filled: str = "0"


@dataclass
class AccountSummary:
    collateral: str
    available: str
    unrealized_pnl: str
    # USDC free + haircut multi-asset margin (unified). Use for max order size.
    trade_available: str = "0"
    positions: list[Position] = field(default_factory=list)
    open_orders: list[OpenOrder] = field(default_factory=list)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "collateral": self.collateral,
            "available": self.available,
            "trade_available": self.trade_available,
            "unrealized_pnl": self.unrealized_pnl,
            "positions": [
                {
                    "market_index": p.market_index,
                    "symbol": p.symbol,
                    "size": p.size,
                    "entry_price": p.entry_price,
                    "mark_price": p.mark_price,
                    "unrealized_pnl": p.unrealized_pnl,
                    "leverage": p.leverage,
                    "margin_mode": p.margin_mode,
                    "liquidation_price": p.liquidation_price,
                    "funding_paid": p.funding_paid,
                    "allocated_margin": p.allocated_margin,
                    "side": p.side,
                }
                for p in self.positions
            ],
            "open_orders": [
                {
                    # Strings: JS cannot safely represent Lighter order_index as number.
                    "order_index": str(o.order_index),
                    "client_order_index": str(o.client_order_index),
                    "market_index": o.market_index,
                    "symbol": o.symbol,
                    "side": o.side,
                    "price": o.price,
                    "size": o.size,
                    "remaining": o.remaining,
                    "filled": o.filled,
                    "order_type": o.order_type,
                    "reduce_only": o.reduce_only,
                }
                for o in self.open_orders
            ],
        }


def to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass
class MarginAssetMeta:
    """Haircut params for unified multi-asset margin (from assetDetails)."""

    symbol: str
    loan_to_value: float
    index_price: float
    margin_mode: str


def multi_asset_haircut_usd(assets: Any, details: dict[str, MarginAssetMeta]) -> float:
    """LTV-discounted USD value of non-stable margin balances (e.g. 1 ETH × index × 0.7)."""
    if not assets or not details:
        return 0.0
    if isinstance(assets, dict):
        rows: list[Any] = list(assets.values())
    elif isinstance(assets, list):
        rows = assets
    else:
        return 0.0
    total = 0.0
    for item in rows:
        if isinstance(item, dict):
            sym = str(item.get("symbol") or "").upper()
            mode = str(item.get("margin_mode") or "").lower()
            bal = to_float(item.get("margin_balance"))
        else:
            sym = str(getattr(item, "symbol", "") or "").upper()
            mode = str(getattr(item, "margin_mode", "") or "").lower()
            bal = to_float(getattr(item, "margin_balance", 0))
        if not sym or sym in {"USDC", "USDG"}:
            continue
        if mode not in {"enabled", "1", "true"}:
            continue
        if bal <= 0:
            continue
        meta = details.get(sym)
        if not meta or meta.loan_to_value <= 0 or meta.index_price <= 0:
            continue
        total += bal * meta.index_price * meta.loan_to_value
    return total


def margin_fraction_to_leverage(imf: int, default: int = 10) -> int:
    """Convert a 10_000-scale initial margin fraction to integer leverage."""
    if imf <= 0:
        return default
    return max(1, min(100, 10_000 // imf))


# Integer leverages whose IMF is exact: 10_000 / lev.
# 3x → IMF 3333, which Lighter rejects as invalid.
CANONICAL_LEVERAGES = (1, 2, 4, 5, 8, 10, 16, 20, 25, 40, 50, 80, 100)


def canonical_leverages(min_imf: int) -> list[int]:
    max_lev = margin_fraction_to_leverage(min_imf, 20)
    return [x for x in CANONICAL_LEVERAGES if x <= max_lev]


def leverage_to_imf(leverage: int, min_imf: int) -> int:
    if leverage < 1:
        raise ValueError("leverage must be at least 1x")
    imf = 10_000 // leverage
    return min(10_000, max(imf, min_imf))


def imf_to_leverage(value: Any, default: int = 10) -> int:
    """Map Lighter initial_margin_fraction to integer leverage.

    The account API returns a percent string such as ``"2.00"`` (2% → 50x)
    or ``"20.00"`` (20% → 5x). Values above 100 are treated as 10_000-scale
    fractions used when signing ``update_leverage``.
    """
    imf = to_float(value, 0.0)
    if imf <= 0:
        return default
    scale = 10_000.0 if imf > 100 else 100.0
    return max(1, min(100, round(scale / imf)))


def format_decimal(value: int | str | float, decimals: int) -> str:
    d = Decimal(str(value)) / (Decimal(10) ** decimals)
    return fmt_decimal(d) or "0"


def parse_to_int(value: str | float, decimals: int) -> int:
    d = Decimal(str(value)) * (Decimal(10) ** decimals)
    return int(d.to_integral_value(rounding=ROUND_DOWN))


def from_scaled(value: int, decimals: int) -> Decimal:
    return Decimal(value) / (Decimal(10) ** decimals)


def maker_min_base(min_base: float, min_quote: float, price: Decimal | None) -> Decimal:
    """Lighter applies the stricter of min base and min quote for maker orders."""
    floor = Decimal(str(min_base or 0))
    quote = Decimal(str(min_quote or 0))
    if price is not None and price > 0 and quote > 0:
        floor = max(floor, quote / price)
    return floor
