from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from mayedge import db as store
from mayedge import desk, feed_health
from mayedge.alive import last_down, mark_clean, note_boot, start_alive
from mayedge.api.guard import BrowserGuard
from mayedge.api.routes import include_api
from mayedge.api.spa import mount_spa
from mayedge.api.turn import LoopTurn, breathe
from mayedge.api.ws import BroadcastFanout, manager, send_json
from mayedge.auto_kill import auto_kill
from mayedge.backup import health as backup_health
from mayedge.backup import start_backup
from mayedge.config import settings
from mayedge.heartbeat import heartbeat_view, start_heartbeat
from mayedge.journal_sync import note_fill
from mayedge.journal_sync import start as start_journal
from mayedge.journal_sync import stop as stop_journal
from mayedge.kill import FLATTEN_SLIPPAGE, KillResult, kill
from mayedge.lighter.account import account_service, set_fill_listener
from mayedge.lighter.budget import KILL_LANE, budget, start_budget_publish
from mayedge.lighter.errors import VenueBlocked
from mayedge.lighter.gateway import gateway
from mayedge.lighter.orders import order_service
from mayedge.loop_watch import set_freeze_emitter, start_loop_watch
from mayedge.loop_watch import snapshot as loop_lag_snapshot
from mayedge.portfolio_sync import start as start_portfolio_sync
from mayedge.portfolio_sync import stop as stop_portfolio_sync
from mayedge.push import TelegramPusher, boot_text, freeze_text, load_push_settings
from mayedge.tone_compute import close as close_tone_pool

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


def _cached_upnl() -> float | None:
    cached = account_service.cached_account_payload()
    if not isinstance(cached, dict):
        return None
    raw: Any = cached.get("unrealized_pnl")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


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
    boot_ms = int(time.time() * 1000)
    down = await asyncio.to_thread(note_boot, boot_ms, load_push_settings().down_after_s)
    watch = start_loop_watch()
    backup = None
    budget_watch = None
    alive = None
    heart = None
    fanout = BroadcastFanout(manager.broadcast)
    fanout.start()
    pusher = TelegramPusher.from_settings()
    app.state.pusher = pusher
    await pusher.start()

    def publish(msg: dict[str, Any]) -> None:
        fanout.push(msg)
        pusher.on_desk_msg(msg)

    def emit_freeze(event: dict[str, Any]) -> None:
        live = feed_health.snapshot().get("account_ws") == "live"
        text = freeze_text(
            int(event["from"]),
            int(event["to"]),
            positions=_open_position_count() if live else 0,
            upnl=_cached_upnl(),
            account_live=live,
        )
        publish({**event, "text": text})

    desk.set_broadcast(publish)
    feed_health.set_emitter(publish)
    set_freeze_emitter(emit_freeze)
    budget_watch = start_budget_publish(publish)
    alive = start_alive()
    heart = start_heartbeat()
    auto_kill.start(run_kill=run_kill, emit=publish, positions=_cached_positions)
    gateway.subscribe(auto_kill.on_gateway)
    set_fill_listener(note_fill)
    start_journal()
    start_portfolio_sync()
    await desk.start()
    await desk.restore()
    backup = start_backup(pusher)
    app.state.backup = backup
    try:
        from mayedge.api.routes.journal import warm as warm_journal

        await warm_journal()
    except Exception:
        logger.exception("journal warm failed")
    n_algos = len(desk.algo_book().get("working") or [])
    pusher.push(
        "boot",
        boot_text(settings.lighter_network.value, n_algos, _open_position_count(), down),
        urgent=down is not None,
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
        close_tone_pool()
        if backup is not None:
            await backup.stop()
        await watch.stop()
        set_freeze_emitter(None)
        for task in (budget_watch, alive, heart):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        await asyncio.to_thread(mark_clean, int(time.time() * 1000))
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
    app.add_middleware(
        BrowserGuard,
        allowed_hosts=settings.allowed_hosts,
        allowed_origins=settings.cors_origins,
    )
    # Added last, so it runs first. One handler per turn, ahead of the guard.
    app.add_middleware(LoopTurn)

    @app.exception_handler(VenueBlocked)
    async def _venue_blocked(_request: Request, exc: VenueBlocked) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "network": settings.lighter_network.value,
            "trading_enabled": order_service.enabled,
            "backup": backup_health(),
            "budget": {k: v for k, v in budget.snapshot().items() if k != "type"},
            "last_down": last_down(),
            "heartbeat": heartbeat_view(),
            **loop_lag_snapshot(),
            **{k: v for k, v in feed_health.snapshot().items() if k != "type"},
        }

    include_api(app)

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        await manager.connect(ws)
        try:
            await breathe()
            markets = [m.as_public_dict() for m in gateway.list_markets()]
            await send_json(
                ws,
                {
                    "type": "init",
                    "network": settings.lighter_network.value,
                    "trading_enabled": order_service.enabled,
                    "markets": markets,
                },
            )
            acct = account_service.cached_account_payload()
            if acct:
                payload = dict(acct)
                payload.pop("venue", None)
                await send_json(ws, payload)
            await breathe()
            book = desk.algo_book()
            await send_json(ws, book)
            await send_json(ws, auto_kill.view())
            await send_json(ws, feed_health.snapshot())
            await send_json(ws, budget.snapshot())
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
