"""What the desk API answers, for the OpenAPI document the web types are generated from.

Routes name these in ``responses=`` only: they document a shape and never filter or
coerce what a route returns. Tests validate real answers against them with extra keys
forbidden, so a field added on one side and not the other fails CI.
Decimal amounts travel as strings.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

Kind = Literal["perps", "spot", "llp", "staking"]


class _Shape(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ── Journal (docs/journal-rules.md) ──────────────────────────────────────


class JournalFill(_Shape):
    trade_id: str
    ts: int
    side: str
    price: str
    size: str
    fee: str
    pnl: str
    is_maker: bool
    closing: bool


class JournalTrip(_Shape):
    trip_key: str
    market_index: int
    symbol: str
    side: Literal["long", "short"]
    open_ts: int
    close_ts: int | None
    size: str
    avg_in: str | None
    avg_out: str | None
    pnl: str
    fees: str
    funding: str
    net: str
    algo: str
    algo_id: str | None
    r: str | None
    partial: bool
    partial_reason: str | None
    open: bool
    upnl: str | None
    note: str
    tags: list[str]
    fills: list[JournalFill]


class JournalTrips(_Shape):
    trips: list[JournalTrip]


class JournalSide(_Shape):
    count: int
    win_rate: str | None
    net: str


class JournalCurvePoint(_Shape):
    ts: int
    net: str


class JournalSummaryGroup(_Shape):
    key: str
    count: int
    wins: int
    losses: int
    win_rate: str | None
    gross_pnl: str
    fees: str
    funding: str
    net: str
    avg_win: str | None
    avg_loss: str | None
    profit_factor: str | None
    expectancy: str | None
    largest_win: str | None
    largest_loss: str | None
    maker_share: str | None
    avg_r: str | None
    total_r: str | None
    # How many Round trips have an R: only Planner runs with a stored stop do.
    r_count: int
    max_drawdown: str | None
    payoff_ratio: str | None
    breakeven_win_rate: str | None
    notional: str
    net_bps: str | None
    recovery_factor: str | None
    max_win_streak: int
    max_loss_streak: int
    current_streak: int
    avg_hold_win_s: str | None
    avg_hold_loss_s: str | None
    long: JournalSide | None
    short: JournalSide | None
    trading_days: int
    green_days: int
    best_day: str | None
    worst_day: str | None
    curve: list[JournalCurvePoint]


class JournalSummary(_Shape):
    range: str
    group: str
    groups: list[JournalSummaryGroup]


class JournalNote(_Shape):
    trip_key: str
    note: str
    tags: list[str]


class JournalExcursion(_Shape):
    """MAE and MFE from the average entry, at a bar size; all None when no bar covers the trip."""

    trip_key: str
    open: bool
    resolution: str | None
    mae_pct: str | None
    mfe_pct: str | None
    mae_usd: str | None
    mfe_usd: str | None


class JournalSync(_Shape):
    started: bool
    last_synced_at: int | None


class OpenTripRealized(_Shape):
    market_index: int
    symbol: str
    side: Literal["long", "short"]
    trip_key: str
    open_ts: int
    realized: str
    pnl: str
    fees: str
    funding: str
    net: str
    partial: bool


class JournalOpen(_Shape):
    type: Literal["journal_open"]
    positions: list[OpenTripRealized]


# ── Portfolio (docs/portfolio-rules.md) ──────────────────────────────────


class PortfolioKindNow(_Shape):
    value: str | None
    value_at_open: str | None
    change: str | None
    change_pct: str | None
    flows: str | None


class PortfolioKinds(_Shape):
    perps: PortfolioKindNow
    spot: PortfolioKindNow
    llp: PortfolioKindNow
    staking: PortfolioKindNow


class PortfolioMismatch(_Shape):
    kind: Kind
    drift: str | None


class PortfolioSpot(_Shape):
    symbol: str
    qty: str | None
    price: str | None
    value: str | None
    upnl: str | None


class PortfolioPool(_Shape):
    pool: int
    kind: Kind
    shares: str | None
    units: str | None
    unit: str
    value: str | None
    apy: str | None
    principal: str | None


class PortfolioUnlock(_Shape):
    asset_index: int
    amount: str | None
    unlock_ms: int


class PortfolioCollateral(_Shape):
    symbol: str
    qty: str | None
    price: str | None
    value: str | None


class PortfolioMarginPart(_Shape):
    symbol: str
    # The USDC cross portfolio, with the open uPnL in it; otherwise a collateral asset at its LTV.
    cross: bool
    qty: str | None
    price: str | None
    ltv: str | None
    value: str | None


class PortfolioMargin(_Shape):
    """Buying power, never part of a value (portfolio-rules N10)."""

    total: str | None
    parts: list[PortfolioMarginPart]


class PortfolioPerps(_Shape):
    collateral: list[PortfolioCollateral]
    upnl: str | None
    margin: PortfolioMargin | None


class PortfolioNow(_Shape):
    ts: int
    open: int
    total: PortfolioKindNow
    kinds: PortfolioKinds
    mismatch: list[PortfolioMismatch]
    spot: list[PortfolioSpot]
    pools: list[PortfolioPool]
    perps: PortfolioPerps
    spot_gap: str | None
    unlocks: list[PortfolioUnlock]


class PortfolioPoint(_Shape):
    ts: int
    total: str | None
    perps: str | None
    spot: str | None
    llp: str | None
    staking: str | None


class PortfolioFlow(_Shape):
    ts: int
    kind: Kind
    amount: str | None


class PortfolioHistory(_Shape):
    range: str
    resolution: Literal["1h", "1d"]
    points: list[PortfolioPoint]
    flows: list[PortfolioFlow]


class PortfolioDayKinds(_Shape):
    perps: str | None
    spot: str | None
    llp: str | None
    staking: str | None


class PortfolioDay(_Shape):
    day: str
    start: int
    kinds: PortfolioDayKinds
    total: str | None


class PortfolioDays(_Shape):
    range: str
    days: list[PortfolioDay]


def documents(model: type[BaseModel]) -> dict[int | str, dict[str, object]]:
    """The ``responses=`` argument that documents a 200 without touching the answer."""
    return {200: {"model": model}}
