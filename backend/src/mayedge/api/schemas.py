from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

TradeSide = Literal["buy", "sell"]


class MarketOrderRequest(BaseModel):
    market_index: int
    side: TradeSide
    size: str
    slippage: float = Field(default=0.01, gt=0, le=0.05)
    reduce_only: bool = False


class LimitOrderRequest(BaseModel):
    market_index: int
    side: TradeSide
    size: str
    price: str
    time_in_force: Literal["gtt", "ioc", "post_only"] = "gtt"
    reduce_only: bool = False


class TwapOrderRequest(BaseModel):
    market_index: int
    side: TradeSide
    size: str
    duration_seconds: int = Field(ge=300, le=2_592_000)
    max_slippage: float = Field(default=0.01, gt=0, le=0.05)
    reduce_only: bool = False


class ConditionalLeg(BaseModel):
    kind: Literal["market", "limit"]
    trigger: str
    price: str | None = None


class StopTakeRequest(BaseModel):
    market_index: int
    side: TradeSide
    size: str
    sl: ConditionalLeg | None = None
    tp: ConditionalLeg | None = None
    slippage: float = Field(default=0.01, gt=0, le=0.05)


class CancelOrderRequest(BaseModel):
    market_index: int
    order_index: int | str

    def order_index_int(self) -> int:
        return int(self.order_index)


class AmendOrderRequest(BaseModel):
    market_index: int
    order_index: int | str
    price: str
    size: str | None = None

    def order_index_int(self) -> int:
        return int(self.order_index)


class CancelAllRequest(BaseModel):
    market_index: int | None = None


class CancelSideRequest(BaseModel):
    side: TradeSide
    market_index: int | None = None


class LeverageRequest(BaseModel):
    market_index: int
    leverage: int = Field(ge=1, le=100)
    cross: bool = True


class KillRequest(BaseModel):
    flatten: bool = False


class AutoKillRequest(BaseModel):
    armed: bool
    loss_usd: float | None = Field(default=None, gt=0)
    profit_usd: float | None = Field(default=None, gt=0)


class AlgoStopRequest(BaseModel):
    algo_id: str | None = None


class ToneTimeframesRequest(BaseModel):
    timeframes: list[str]


class IdeaTargetIn(BaseModel):
    price: str
    pct: str | None = None


class IdeaCatalystIn(BaseModel):
    text: str = ""
    date: str | None = None


class IdeaBody(BaseModel):
    symbol: str
    side: Literal["long", "short"]
    thesis: str
    conviction: int = 2
    horizon: Literal["scalp", "swing", "position"] = "swing"
    invalidation: str = ""
    trigger: str = ""
    tags: list[str] = Field(default_factory=list)
    catalysts: list[IdeaCatalystIn] = Field(default_factory=list)
    entry_low: str | None = None
    entry_high: str | None = None
    stop: str | None = None
    targets: list[IdeaTargetIn] = Field(default_factory=list)


class IdeaPatch(BaseModel):
    seen_updated_at: int
    symbol: str | None = None
    side: Literal["long", "short"] | None = None
    thesis: str | None = None
    conviction: int | None = None
    horizon: Literal["scalp", "swing", "position"] | None = None
    invalidation: str | None = None
    trigger: str | None = None
    tags: list[str] | None = None
    catalysts: list[IdeaCatalystIn] | None = None
    entry_low: str | None = None
    entry_high: str | None = None
    stop: str | None = None
    targets: list[IdeaTargetIn] | None = None


class IdeaStatusBody(BaseModel):
    status: Literal["watching", "active", "closed", "dropped"]
    outcome: Literal["worked", "failed", "missed", "wrong"] | None = None
    review: str | None = None


class IdeaReviewBody(BaseModel):
    outcome: Literal["worked", "failed", "missed", "wrong"] | None = None
    review: str | None = None


class IdeaLogBody(BaseModel):
    body: str


class IdeaPlannerBody(BaseModel):
    algo_id: str


class IdeaAlertBody(BaseModel):
    kind: Literal["level", "move", "day"]
    price: str | None = None
    pct: str | None = None
    direction: Literal["above", "below", "up", "down", "either"] | None = None
    repeat: bool = False
    note: str = ""
