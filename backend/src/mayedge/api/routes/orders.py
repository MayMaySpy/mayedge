from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from mayedge import desk
from mayedge.api.deps import _order_service, _require_trading, _trade
from mayedge.api.schemas import (
    AmendOrderRequest,
    CancelAllRequest,
    CancelOrderRequest,
    CancelSideRequest,
    LeverageRequest,
    LimitOrderRequest,
    MarketOrderRequest,
    StopTakeRequest,
    TwapOrderRequest,
)

router = APIRouter()


@router.post("/api/orders/market")
async def place_market_order(req: MarketOrderRequest) -> dict[str, Any]:
    _require_trading()
    return await _trade(
        lambda: _order_service().create_market_order(
            req.market_index, req.side, req.size, req.slippage, req.reduce_only
        ),
    )


@router.post("/api/orders/limit")
async def place_limit_order(req: LimitOrderRequest) -> dict[str, Any]:
    _require_trading()
    return await _trade(
        lambda: _order_service().create_limit_order(
            req.market_index,
            req.side,
            req.size,
            req.price,
            req.time_in_force,
            req.reduce_only,
        ),
    )


@router.post("/api/orders/twap")
async def place_twap_order(req: TwapOrderRequest) -> dict[str, Any]:
    _require_trading()
    return await _trade(
        lambda: _order_service().create_twap_order(
            req.market_index,
            req.side,
            req.size,
            req.duration_seconds,
            req.max_slippage,
            req.reduce_only,
        ),
    )


@router.post("/api/orders/sl-tp")
async def place_sl_tp(req: StopTakeRequest) -> dict[str, Any]:
    _require_trading()
    if desk.planner_owns_exit(req.market_index):
        raise HTTPException(409, "Planner owns the exit on this Market")
    if req.sl is not None and desk.trail_stop_owns_stop(req.market_index):
        raise HTTPException(409, "A Trail Stop is this Position's stop")
    return await _trade(
        lambda: _order_service().create_sl_tp(
            req.market_index,
            req.side,
            req.size,
            sl=req.sl.model_dump() if req.sl else None,
            tp=req.tp.model_dump() if req.tp else None,
            slippage=req.slippage,
        ),
    )


@router.post("/api/orders/cancel")
async def cancel_order(req: CancelOrderRequest) -> dict[str, Any]:
    _require_trading()
    return await _trade(
        lambda: _order_service().cancel_order(req.market_index, req.order_index_int()),
    )


@router.post("/api/orders/modify")
async def amend_order(req: AmendOrderRequest) -> dict[str, Any]:
    _require_trading()
    return await _trade(
        lambda: _order_service().amend_ticket(
            req.market_index,
            req.order_index_int(),
            req.price,
            size=req.size,
        ),
    )


@router.post("/api/orders/cancel-side")
async def cancel_side(req: CancelSideRequest) -> dict[str, Any]:
    _require_trading()
    return await _trade(lambda: _order_service().cancel_tickets(req.side, req.market_index))


@router.post("/api/orders/cancel-all")
async def cancel_all(req: CancelAllRequest) -> dict[str, Any]:
    _require_trading()
    await desk.pause_for_market(req.market_index)
    return await _trade(lambda: _order_service().cancel_all_orders(req.market_index))


@router.post("/api/orders/cancel-all/{market_index}")
async def cancel_all_market(market_index: int) -> dict[str, Any]:
    _require_trading()
    await desk.pause_for_market(market_index)
    return await _trade(lambda: _order_service().cancel_all_orders(market_index))


@router.post("/api/leverage")
async def update_leverage(req: LeverageRequest) -> dict[str, Any]:
    _require_trading()
    return await _trade(
        lambda: _order_service().update_leverage(req.market_index, req.leverage, req.cross),
    )
