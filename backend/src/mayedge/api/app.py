from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from mayedge import db as store
from mayedge import desk, feed_health
from mayedge.api.guard import BrowserGuard
from mayedge.api.routes import include_api
from mayedge.api.spa import mount_spa
from mayedge.api.ws import BroadcastFanout, manager, send_json
from mayedge.auto_kill import auto_kill
from mayedge.config import settings
from mayedge.journal_sync import note_fill
from mayedge.journal_sync import start as start_journal
from mayedge.journal_sync import stop as stop_journal
from mayedge.kill import FLATTEN_SLIPPAGE, KillResult, kill
from mayedge.lighter.account import account_service, set_fill_listener
from mayedge.lighter.budget import KILL_LANE, budget
from mayedge.lighter.errors import VenueBlocked
from mayedge.lighter.gateway import gateway
from mayedge.lighter.orders import order_service
from mayedge.portfolio_sync import start as start_portfolio_sync
from mayedge.portfolio_sync import stop as stop_portfolio_sync
from mayedge.push import TelegramPusher, boot_text

logger = logging.getLogger(__name__)


class _AllAlgos:
    async def stop(self) -> None:
        await desk.stop_algo()


async def _account_summary_for_kill():
    try:
        return await order_service.get_account_summary()
    except Exception:
        logger.warning("kill account summary REST failed; using cache", exc_info=True)
        return account_service.cached_summary()


def _cached_positions() -> list[Any]:
    cached = account_service.cached_account_payload()
    return list((cached or {}).get("positions") or [])


def _open_position_count() -> int:
    n = 0
    for pos in _cached_positions():
        raw: Any = pos.get("size") if isinstance(pos, dict) else getattr(pos, "size", 0)
        if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
            continue
        try:
            if float(raw) != 0:
                n += 1
        except ValueError:
            continue
    return n


async def run_kill(*, flatten: bool, slippage: float = FLATTEN_SLIPPAGE) -> KillResult:
    # Kill is sent even when the local budget is full or cooling.
    token = budget.enter_lane(KILL_LANE)
    try:
        return await kill(
            flatten=flatten,
            algos=_AllAlgos(),
            orders=order_service,
            get_account_summary=_account_summary_for_kill,
            slippage=slippage,
        )
    finally:
        budget.leave_lane(token)


@asynccontextmanager
async def lifespan(app: FastAPI):
    fanout = BroadcastFanout(manager.broadcast)
    fanout.start()
    pusher = TelegramPusher.from_settings()
    app.state.pusher = pusher
    await pusher.start()

    def publish(msg: dict[str, Any]) -> None:
        fanout.push(msg)
        pusher.on_desk_msg(msg)

    desk.set_broadcast(publish)
    feed_health.set_emitter(publish)
    auto_kill.start(run_kill=run_kill, emit=publish, positions=_cached_positions)
    gateway.subscribe(auto_kill.on_gateway)
    set_fill_listener(note_fill)
    start_journal()
    start_portfolio_sync()
    await desk.start()
    await desk.restore()
    n_algos = len(desk.algo_book().get("working") or [])
    pusher.push(
        "boot",
        boot_text(settings.lighter_network.value, n_algos, _open_position_count()),
    )
    try:
        yield
    finally:
        set_fill_listener(None)
        await stop_journal()
        await stop_portfolio_sync()
        gateway.unsubscribe(auto_kill.on_gateway)
        auto_kill.stop()
        feed_health.set_emitter(None)
        desk.set_broadcast(None)
        await pusher.stop()
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
    # Added last, so it runs first.
    app.add_middleware(
        BrowserGuard,
        allowed_hosts=settings.allowed_hosts,
        allowed_origins=settings.cors_origins,
    )

    @app.exception_handler(VenueBlocked)
    async def _venue_blocked(_request: Request, exc: VenueBlocked) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "network": settings.lighter_network.value,
            "trading_enabled": order_service.enabled,
            **{k: v for k, v in feed_health.snapshot().items() if k != "type"},
        }

    include_api(app)

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
            await send_json(ws, auto_kill.view())
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
                try:
                    symbol = msg.get("symbol", settings.default_market_symbol)
                    idx = gateway.resolve_subscribe_market(symbol, msg.get("market_index"))
                    await gateway.set_active_market(idx)
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
                except WebSocketDisconnect:
                    raise
                except Exception:
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
