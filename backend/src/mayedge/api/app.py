from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from mayedge import db as store
from mayedge import desk, feed_health
from mayedge.algos.chase import ChaseIcebergParams
from mayedge.algos.twap.plan import AdvancedTwapParams
from mayedge.api.schemas import (
    AdvancedTwapStartRequest,
    CancelAllRequest,
    CancelOrderRequest,
    ChaseStartRequest,
    ChaseStopRequest,
    KillRequest,
    LeverageRequest,
    LimitOrderRequest,
    MarketOrderRequest,
    TwapOrderRequest,
)
from mayedge.api.spa import mount_spa
from mayedge.api.ws import BroadcastFanout, manager, send_json
from mayedge.config import settings
from mayedge.kill import KillResult, kill
from mayedge.lighter.account import account_service
from mayedge.lighter.gateway import gateway
from mayedge.lighter.orders import order_service
from mayedge.numbers import parse_decimal

logger = logging.getLogger(__name__)


class _AllAlgos:
    async def stop(self) -> None:
        await desk.chase_book.stop()
        await desk.twap_book.stop()


async def run_kill(*, flatten: bool) -> KillResult:
    return await kill(
        flatten=flatten,
        chase=_AllAlgos(),
        orders=order_service,
        get_account_summary=order_service.get_account_summary,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    fanout = BroadcastFanout(manager.broadcast)
    fanout.start()

    def on_desk_msg(msg: dict[str, Any]) -> None:
        fanout.push(msg)

    def on_feed_health(msg: dict[str, Any]) -> None:
        fanout.push(msg)

    desk.set_broadcast(on_desk_msg)
    feed_health.set_emitter(on_feed_health)
    await desk.start()
    await desk.restore()
    try:
        yield
    finally:
        feed_health.set_emitter(None)
        desk.set_broadcast(None)
        await fanout.stop()
        await desk.stop()
        store.close_db()


def create_app() -> FastAPI:
    app = FastAPI(title="Mayedge", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def _require_trading() -> None:
        if not order_service.enabled:
            raise HTTPException(503, "Trading not configured. Set API credentials in .env")

    async def _trade(fn):
        _require_trading()
        try:
            result = await fn()
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        order_service.kick_refresh()
        return result

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "network": settings.lighter_network.value,
            "trading_enabled": order_service.enabled,
            **{k: v for k, v in feed_health.snapshot().items() if k != "type"},
        }

    @app.get("/api/alerts")
    async def get_alerts(limit: int = 200) -> list[dict[str, Any]]:
        cap = max(1, min(int(limit), 1000))
        return gateway.recent_alerts()[:cap]

    @app.get("/api/liquidations")
    async def get_liquidations(
        limit: int = 200,
        min_usd: float | None = None,
        market_index: int | None = None,
    ) -> list[dict[str, Any]]:
        cap = max(1, min(int(limit), 1000))
        ring = gateway.recent_liquidations()
        if ring and min_usd is None and market_index is None:
            return ring[:cap]
        return store.list_liquidations(limit=limit, min_usd=min_usd, market_index=market_index)

    @app.get("/api/markets")
    async def list_markets() -> list[dict[str, Any]]:
        return [m.as_public_dict() for m in gateway.list_markets()]

    @app.get("/api/markets/{symbol}")
    async def get_market(symbol: str) -> dict[str, Any]:
        meta = gateway.get_market(symbol)
        if not meta:
            raise HTTPException(404, "Market not found")
        return meta.as_public_dict()

    @app.get("/api/candles/{symbol}")
    async def get_candles(symbol: str, resolution: str = "1m", count: int = 500) -> list[dict]:
        idx = gateway.resolve_market_index(symbol)
        n = min(max(int(count), 1), 3600)
        candles = await gateway.get_candles(idx, resolution, n)
        return [
            {
                "time": c.time,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in candles
        ]

    @app.post("/api/markets/{symbol}/activate")
    async def activate_market(symbol: str) -> dict[str, str]:
        idx = gateway.resolve_market_index(symbol)
        await gateway.set_active_market(idx)
        return {"status": "ok", "market_index": str(idx)}

    @app.get("/api/account")
    async def get_account() -> dict[str, Any]:
        cached = account_service.cached_account_payload()
        if cached:
            out = dict(cached)
            out.pop("type", None)
            out.pop("venue", None)
            return out
        summary = await order_service.get_account_summary()
        return summary.to_public_dict()

    @app.get("/api/account/trades")
    async def get_account_trades(
        market_index: int | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        if not settings.lighter_account_index:
            raise HTTPException(400, "Account not configured")
        try:
            return await order_service.get_account_trades(
                market_id=market_index,
                cursor=cursor,
                limit=limit,
            )
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @app.get("/api/account/funding")
    async def get_account_funding(
        market_index: int | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        if not settings.lighter_account_index:
            raise HTTPException(400, "Account not configured")
        try:
            return await order_service.get_account_funding(
                market_id=market_index,
                cursor=cursor,
                limit=limit,
            )
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @app.post("/api/orders/market")
    async def place_market_order(req: MarketOrderRequest) -> dict[str, Any]:
        _require_trading()
        return await _trade(
            lambda: order_service.create_market_order(
                req.market_index, req.side, req.size, req.slippage, req.reduce_only
            ),
        )

    @app.post("/api/orders/limit")
    async def place_limit_order(req: LimitOrderRequest) -> dict[str, Any]:
        _require_trading()
        return await _trade(
            lambda: order_service.create_limit_order(
                req.market_index,
                req.side,
                req.size,
                req.price,
                req.time_in_force,
                req.reduce_only,
            ),
        )

    @app.post("/api/orders/twap")
    async def place_twap_order(req: TwapOrderRequest) -> dict[str, Any]:
        _require_trading()
        return await _trade(
            lambda: order_service.create_twap_order(
                req.market_index,
                req.side,
                req.size,
                req.duration_seconds,
                req.max_slippage,
                req.reduce_only,
            ),
        )

    @app.post("/api/orders/cancel")
    async def cancel_order(req: CancelOrderRequest) -> dict[str, Any]:
        _require_trading()
        return await _trade(
            lambda: order_service.cancel_order(req.market_index, req.order_index_int()),
        )

    @app.post("/api/orders/cancel-all")
    async def cancel_all(req: CancelAllRequest) -> dict[str, Any]:
        _require_trading()
        await desk.chase_book.pause_for_market(req.market_index)
        await desk.twap_book.pause_for_market(req.market_index)
        return await _trade(lambda: order_service.cancel_all_orders(req.market_index))

    @app.post("/api/orders/cancel-all/{market_index}")
    async def cancel_all_market(market_index: int) -> dict[str, Any]:
        _require_trading()
        await desk.chase_book.pause_for_market(market_index)
        await desk.twap_book.pause_for_market(market_index)
        return await _trade(lambda: order_service.cancel_all_orders(market_index))

    @app.post("/api/leverage")
    async def update_leverage(req: LeverageRequest) -> dict[str, Any]:
        _require_trading()
        return await _trade(
            lambda: order_service.update_leverage(req.market_index, req.leverage, req.cross),
        )

    @app.get("/api/algos")
    async def get_algos() -> dict[str, Any]:
        return desk.algo_book()

    @app.get("/api/algos/chase-iceberg")
    async def get_chase() -> dict[str, Any]:
        return desk.chase_book.to_dict()

    @app.post("/api/algos/chase-iceberg/start")
    async def start_chase(req: ChaseStartRequest) -> dict[str, Any]:
        _require_trading()
        book = desk.chase_book
        try:
            params = ChaseIcebergParams(
                side=req.side,
                qty=parse_decimal(req.qty),
                display_qty=parse_decimal(req.display_qty),
                offset_bps=parse_decimal(req.offset_bps),
                price_floor=parse_decimal(req.price_floor),
                price_ceiling=parse_decimal(req.price_ceiling),
            )
            await book.start(
                market_index=req.market_index,
                params=params,
                reduce_only=req.reduce_only,
            )
        except (ValueError, ArithmeticError) as e:
            raise HTTPException(400, str(e)) from e
        return desk.algo_book()

    @app.post("/api/algos/chase-iceberg/stop")
    async def stop_chase(req: ChaseStopRequest = ChaseStopRequest()) -> dict[str, Any]:
        return await desk.stop_algo(req.algo_id if req else None)

    @app.post("/api/algos/chase-iceberg/pause")
    async def pause_chase(req: ChaseStopRequest) -> dict[str, Any]:
        _require_trading()
        if not req.algo_id:
            raise HTTPException(400, "algo_id required")
        try:
            return await desk.pause_algo(req.algo_id)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @app.post("/api/algos/chase-iceberg/unpause")
    async def unpause_chase(req: ChaseStopRequest) -> dict[str, Any]:
        _require_trading()
        if not req.algo_id:
            raise HTTPException(400, "algo_id required")
        try:
            return await desk.unpause_algo(req.algo_id)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @app.post("/api/algos/advanced-twap/start")
    async def start_advanced_twap(req: AdvancedTwapStartRequest) -> dict[str, Any]:
        _require_trading()
        try:
            max_price = parse_decimal(req.max_price) if req.max_price else None
            max_index = parse_decimal(req.max_index_pct) if req.max_index_pct else None
            params = AdvancedTwapParams(
                side=req.side,
                qty=parse_decimal(req.qty),
                duration_seconds=req.duration_seconds,
                frequency_seconds=req.frequency_seconds,
                style=req.style,
                randomize=req.randomize,
                max_price=max_price,
                max_index_pct=max_index,
            )
            await desk.twap_book.start(
                market_index=req.market_index,
                params=params,
                reduce_only=req.reduce_only,
            )
        except (ValueError, ArithmeticError) as e:
            raise HTTPException(400, str(e)) from e
        return desk.algo_book()

    @app.post("/api/kill")
    async def kill_switch(req: KillRequest) -> dict[str, Any]:
        result = await run_kill(flatten=req.flatten)
        return {**result.as_dict(), "algos": desk.algo_book()}

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        await manager.connect(ws)
        try:
            await send_json(
                ws,
                {
                    "type": "init",
                    "network": settings.lighter_network.value,
                    "trading_enabled": order_service.enabled,
                    "markets": [m.as_public_dict() for m in gateway.list_markets()],
                },
            )
            acct = account_service.cached_account_payload()
            if acct:
                payload = dict(acct)
                payload.pop("venue", None)
                await send_json(ws, payload)
            await send_json(ws, desk.algo_book())
            await send_json(ws, feed_health.snapshot())
            alerts = gateway.recent_alerts()
            if alerts:
                await send_json(ws, {"type": "alerts", "events": alerts})
            liqs = gateway.recent_liquidations()
            if liqs:
                await send_json(ws, {"type": "liquidations", "items": liqs})
            while True:
                data = await ws.receive_text()
                try:
                    msg = json.loads(data)
                except json.JSONDecodeError:
                    continue
                kind = msg.get("type")
                if kind == "resync_book":
                    gateway.request_book_snapshot()
                    continue
                if kind != "subscribe_market":
                    continue
                candles_task: asyncio.Task[Any] | None = None
                try:
                    symbol = msg.get("symbol", settings.default_market_symbol)
                    idx = gateway.resolve_subscribe_market(symbol, msg.get("market_index"))
                    await gateway.set_active_market(idx)
                    candles_task = asyncio.create_task(gateway.get_candles(idx))
                    try:
                        async with asyncio.timeout(3.0):
                            got_book = await gateway.wait_for_book(idx)
                    except TimeoutError:
                        got_book = False
                    book = gateway.order_book_payload(idx)
                    if book:
                        book.pop("venue", None)
                        await send_json(ws, book)
                    else:
                        logger.warning(
                            "subscribe_market %s: no order_book after wait (got_book=%s)",
                            symbol,
                            got_book,
                        )
                        gateway.request_book_snapshot(idx)
                    trades = gateway.trades_payload(idx)
                    if trades:
                        trades.pop("venue", None)
                        await send_json(ws, trades)
                    candles = await candles_task
                    await send_json(
                        ws,
                        {
                            "type": "candles",
                            "market_index": idx,
                            "candles": [
                                {
                                    "time": c.time,
                                    "open": c.open,
                                    "high": c.high,
                                    "low": c.low,
                                    "close": c.close,
                                    "volume": c.volume,
                                }
                                for c in candles
                            ],
                        },
                    )
                except WebSocketDisconnect:
                    if candles_task is not None and not candles_task.done():
                        candles_task.cancel()
                    raise
                except Exception:
                    if candles_task is not None and not candles_task.done():
                        candles_task.cancel()
                    logger.exception("subscribe_market failed")
        except WebSocketDisconnect:
            pass
        except RuntimeError as e:
            if "close message" in str(e).lower() or "not connected" in str(e).lower():
                pass
            else:
                logger.exception("websocket error")
        except Exception:
            logger.exception("websocket error")
        finally:
            manager.disconnect(ws)

    mount_spa(app)
    return app


app = create_app()
