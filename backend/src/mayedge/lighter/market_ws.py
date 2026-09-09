from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from typing import TYPE_CHECKING, Any

import websockets

from mayedge import feed_health
from mayedge.config import settings
from mayedge.lighter.channels import message_market_index, parse_channel_market
from mayedge.lighter.liquidations import LiquidationFeed
from mayedge.lighter.models import Trade

if TYPE_CHECKING:
    from mayedge.lighter.gateway import LighterGateway

logger = logging.getLogger(__name__)

_SUB_BATCH = 40
_SUB_MIN_INTERVAL = 60.0 / 150.0
_PING_EVERY = 25.0
_SILENCE_S = 45.0


async def ws_send(ws: Any, payload: dict[str, Any]) -> None:
    await ws.send(json.dumps(payload))


async def run_ws_loop(gw: LighterGateway) -> None:
    while True:
        try:
            feed_health.set_market_ws(
                "reconnecting",
                trade_subs=0,
                trade_subs_target=len(gw._trade_subs_target),
            )
            gw._trade_subs.clear()
            await connect_and_stream(gw)
        except asyncio.CancelledError:
            feed_health.set_market_ws("down", trade_subs=0)
            break
        except Exception:
            logger.exception("ws loop error, reconnecting in 3s")
            feed_health.set_market_ws("reconnecting", trade_subs=0)
            gw.unbind_market_ws()
            gw._trade_subs.clear()
            await asyncio.sleep(3)


async def connect_and_stream(gw: LighterGateway) -> None:
    gw._refresh_trade_targets()
    async with websockets.connect(settings.ws_url) as ws:
        sub_task: asyncio.Task[None] | None = None
        ping_task: asyncio.Task[None] | None = None
        watch_task: asyncio.Task[None] | None = None
        try:
            async with gw._lock:
                market_index = gw.bind_market_ws(ws)
                gw._last_msg_at = time.monotonic()
                feed_health.set_market_ws(
                    "live",
                    last_msg_at=int(time.time() * 1000),
                    trade_subs=0,
                    trade_subs_target=len(gw._trade_subs_target),
                )
                async with gw._send_lock:
                    await ws_send(
                        ws, {"type": "subscribe", "channel": f"order_book/{market_index}"}
                    )
                    await ws_send(ws, {"type": "subscribe", "channel": f"candle/{market_index}/1m"})
                    for pinned in list(gw._pinned_books):
                        if pinned != market_index:
                            await ws_send(
                                ws, {"type": "subscribe", "channel": f"order_book/{pinned}"}
                            )
                    await ws_send(ws, {"type": "subscribe", "channel": "market_stats/all"})
                    gw._trade_subs_target.add(market_index)
                    try:
                        await ws_send(ws, {"type": "subscribe", "channel": f"trade/{market_index}"})
                        gw._trade_subs.add(market_index)
                        logger.info("active market trade/%s subscribed", market_index)
                    except Exception:
                        logger.exception("active trade subscribe failed")

            sub_task = asyncio.create_task(pace_trade_subs(gw, ws))
            ping_task = asyncio.create_task(ping_loop(gw, ws))
            watch_task = asyncio.create_task(silence_watchdog(gw, ws))
            async for raw in ws:
                gw._last_msg_at = time.monotonic()
                feed_health.touch_market_msg()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if msg.get("type") == "ping":
                    async with gw._send_lock:
                        await ws_send(ws, {"type": "pong"})
                    continue
                if msg.get("type") == "pong":
                    continue
                await handle_ws_message(gw, msg)
        finally:
            gw.unbind_market_ws()
            for task in (sub_task, ping_task, watch_task):
                if task is None:
                    continue
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task


async def ping_loop(gw: LighterGateway, ws: Any) -> None:
    while True:
        await asyncio.sleep(_PING_EVERY)
        async with gw._send_lock:
            await ws_send(ws, {"type": "ping"})


async def silence_watchdog(gw: LighterGateway, ws: Any) -> None:
    while True:
        await asyncio.sleep(5)
        silent = time.monotonic() - gw._last_msg_at
        if silent >= _SILENCE_S:
            logger.warning("market ws silent for %.0fs — forcing reconnect", silent)
            feed_health.set_market_ws("stale", trade_subs=len(gw._trade_subs))
            with contextlib.suppress(Exception):
                await ws.close()
            return


async def pace_trade_subs(gw: LighterGateway, ws: Any) -> None:
    active = gw._current_market_index
    if active is not None:
        deadline = time.monotonic() + 5.0
        while not gw._books.has_book(active) and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        if not gw._books.has_book(active):
            logger.warning(
                "pacing trades before order_book snapshot market=%s",
                active,
            )
    if active is not None and active not in gw._trade_subs:
        try:
            await gw._focus_gate.wait()
            async with gw._send_lock:
                await ws_send(ws, {"type": "subscribe", "channel": f"trade/{active}"})
                gw._trade_subs.add(active)
        except Exception:
            logger.exception("priority trade subscribe failed for %s", active)

    pending = sorted(gw._trade_subs_target - gw._trade_subs)
    if not pending:
        logger.info(
            "trade subscriptions ready %d/%d",
            len(gw._trade_subs),
            len(gw._trade_subs_target),
        )
        return
    logger.info("pacing %d trade subscriptions (active=%s first)", len(pending), active)
    sent_in_window = 0
    window_start = time.monotonic()
    while True:
        pending_set = gw._trade_subs_target - gw._trade_subs
        if not pending_set:
            break
        remaining = sorted(
            pending_set,
            key=lambda mi: (0 if mi == gw._current_market_index else 1, mi),
        )
        batch = remaining[:_SUB_BATCH]
        for mi in batch:
            await gw._focus_gate.wait()
            now = time.monotonic()
            if now - window_start >= 60:
                window_start = now
                sent_in_window = 0
            if sent_in_window >= 150:
                await asyncio.sleep(max(0.1, 60 - (now - window_start)))
                window_start = time.monotonic()
                sent_in_window = 0
                await gw._focus_gate.wait()
            async with gw._send_lock:
                await ws_send(ws, {"type": "subscribe", "channel": f"trade/{mi}"})
                gw._trade_subs.add(mi)
            sent_in_window += 1
            await asyncio.sleep(_SUB_MIN_INTERVAL)
        feed_health.set_market_ws(
            "live",
            trade_subs=len(gw._trade_subs),
            trade_subs_target=len(gw._trade_subs_target),
        )
        await asyncio.sleep(0.2)
    logger.info(
        "trade subscriptions ready %d/%d",
        len(gw._trade_subs),
        len(gw._trade_subs_target),
    )


async def handle_ws_message(gw: LighterGateway, msg: dict[str, Any]) -> None:
    msg_type = msg.get("type", "")
    if msg_type in ("subscribed/order_book", "update/order_book"):
        await gw._books.handle_message(msg)
    elif msg_type in ("subscribed/trade", "update/trade"):
        await handle_trades(gw, msg, live=msg_type.startswith("update/"))
    elif msg_type in ("subscribed/candle", "update/candle"):
        await handle_candle(gw, msg)
    elif msg_type in ("subscribed/market_stats", "update/market_stats"):
        gw._apply_market_stats(msg)


async def handle_trades(gw: LighterGateway, msg: dict[str, Any], *, live: bool = True) -> None:
    market_index = message_market_index(msg, "trade")
    if market_index is None:
        return

    trades_raw = msg.get("trades") or msg.get("trade") or []
    if isinstance(trades_raw, dict):
        trades_raw = [trades_raw]

    liq_kinds = LiquidationFeed.liq_kinds()
    if live:
        liq_raw = msg.get("liquidation_trades") or []
        if isinstance(liq_raw, dict):
            liq_raw = [liq_raw]
        liq_candidates: list[Any] = list(liq_raw)
        for t in trades_raw:
            if isinstance(t, dict) and str(t.get("type") or "") in liq_kinds:
                liq_candidates.append(t)
        if liq_candidates:
            gw._liqs.ingest(
                market_index,
                liq_candidates,
                get_market=gw.get_market_by_index,
            )

    if market_index != gw._current_market_index:
        return

    if not live and gw._recent_trades.get(market_index):
        return

    new_trades: list[Trade] = []
    for t in trades_raw:
        if not isinstance(t, dict):
            continue
        kind = str(t.get("type") or "trade")
        if kind in liq_kinds:
            continue
        trade = Trade(
            price=str(t.get("price", "")),
            size=str(t.get("size", t.get("amount", ""))),
            side="sell" if t.get("is_maker_ask") or t.get("isAsk") else "buy",
            timestamp=int(t.get("timestamp", t.get("time", 0))),
        )
        new_trades.append(trade)

    if not new_trades:
        return

    existing = gw._recent_trades.setdefault(market_index, [])
    existing = new_trades + existing
    gw._recent_trades[market_index] = existing[:500]

    for trade in sorted(new_trades, key=lambda t: t.timestamp):
        gw._apply_trade_1s(market_index, trade)

    payload = gw.trades_payload(market_index, new_trades)
    if payload:
        gw.broadcast(payload)


async def handle_candle(gw: LighterGateway, msg: dict[str, Any]) -> None:
    market_index = parse_channel_market(msg.get("channel"), "candle")
    if market_index is None:
        market_index = gw._current_market_index
    if market_index is None or market_index != gw._current_market_index:
        return

    candles_raw = msg.get("candles") or []
    if not candles_raw and "candlestick" in msg:
        candles_raw = [msg.get("candlestick")]
    for c in candles_raw:
        if not c:
            continue
        gw.broadcast(
            {
                "type": "candle",
                "market_index": market_index,
                "candle": {
                    "time": int(
                        c.get("timestamp", c.get("t", 0)) // 1000
                        if c.get("timestamp", c.get("t", 0)) > 1e12
                        else c.get("timestamp", c.get("t", 0))
                    ),
                    "open": float(c.get("open", c.get("o", 0))),
                    "high": float(c.get("high", c.get("h", 0))),
                    "low": float(c.get("low", c.get("l", 0))),
                    "close": float(c.get("close", c.get("c", 0))),
                    "volume": float(c.get("volume", c.get("v", 0))),
                },
            }
        )
