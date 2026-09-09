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
    time_in_force: str = "gtt"
    reduce_only: bool = False


class TwapOrderRequest(BaseModel):
    market_index: int
    side: TradeSide
    size: str
    duration_seconds: int = Field(ge=60, le=2_592_000)
    max_slippage: float = Field(default=0.01, gt=0, le=0.05)
    reduce_only: bool = False


class CancelOrderRequest(BaseModel):
    market_index: int
    order_index: int | str

    def order_index_int(self) -> int:
        return int(self.order_index)


class CancelAllRequest(BaseModel):
    market_index: int | None = None


class LeverageRequest(BaseModel):
    market_index: int
    leverage: int = Field(ge=1, le=100)
    cross: bool = True


class KillRequest(BaseModel):
    flatten: bool = False


class ChaseStopRequest(BaseModel):
    algo_id: str | None = None


class ChaseStartRequest(BaseModel):
    market_index: int
    side: TradeSide
    qty: str
    display_qty: str
    offset_bps: str = "4"
    price_floor: str
    price_ceiling: str
    reduce_only: bool = False


class AdvancedTwapStartRequest(BaseModel):
    market_index: int
    side: TradeSide
    qty: str
    duration_seconds: int = Field(ge=60, le=2_592_000)
    frequency_seconds: int = Field(default=5, ge=2, le=3_600)
    style: Literal["passive", "neutral", "aggressive"] = "neutral"
    randomize: bool = True
    max_price: str | None = None
    max_index_pct: str | None = None
    reduce_only: bool = False
