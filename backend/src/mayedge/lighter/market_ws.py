from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
from typing import TYPE_CHECKING, Any

import websockets

from mayedge import feed_health
from mayedge.config import settings
from mayedge.lighter.channels import message_market_index, parse_channel_market, split_ws_type
from mayedge.lighter.errors import venue_down_reason
from mayedge.lighter.liquidations import LiquidationFeed, taker_side
from mayedge.lighter.models import Trade
from mayedge.tone_timeframes import candle_channel_resolution

if TYPE_CHECKING:
    from mayedge.lighter.gateway import LighterGateway

logger = logging.getLogger(__name__)

_SUB_BATCH = 40
_PACE_PER_MIN = 150
_PING_EVERY = 25.0
_SILENCE_S = 45.0
_TONE_CONN_CAP = 450
# Channel index only — `"trade/1"` must not match `"trade/12"`.
_TRADE_CHANNEL_STR = re.compile(r'"channel"\s*:\s*"trade(?:_fe)?(?:@[A-Za-z0-9]+)?[:/](\d+)')
_TRADE_CHANNEL_BYTES = re.compile(_TRADE_CHANNEL_STR.pattern.encode())


def skip_idle_trade(
    raw: str | bytes, focus: int | None, keep: set[int] | frozenset[int] = frozenset()
) -> bool:
    """Drop a non-focused trade frame before ``json.loads``.

    Liquidations and deleverages stay, and so do the market on screen and ``keep``
    (the Markets a Trail on Last follows). Books, stats, and candles do not match
    the trade channel.
    """
    if isinstance(raw, str):
        if "liquidation" in raw or "deleverage" in raw:
            return False
        match = _TRADE_CHANNEL_STR.search(raw)
    else:
        if b"liquidation" in raw or b"deleverage" in raw:
            return False
        match = _TRADE_CHANNEL_BYTES.search(raw)
    if match is None:
        return False
    mi = int(match.group(1))
    return mi != focus and mi not in keep


class SendPacer:
    """Space client WS frames across every connection. 200/min is per IP."""

    def __init__(self, per_min: int = _PACE_PER_MIN) -> None:
        self._interval = 60.0 / per_min
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            slot = self._next if self._next > now else now
            self._next = slot + self._interval
        delay = slot - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)


send_pacer = SendPacer()


async def ws_send(ws: Any, payload: dict[str, Any]) -> None:
    await ws.send(json.dumps(payload))


def _log_ws_error(err: BaseException, what: str) -> None:
    reason = venue_down_reason(err)
    if reason is None:
        logger.exception(what)
        return
    feed_health.note_venue_down(reason)
    logger.warning("%s: Lighter unavailable (%s)", what, reason)


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
        except Exception as e:
            _log_ws_error(e, "ws loop error, reconnecting in 3s")
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
                if skip_idle_trade(raw, gw._current_market_index, gw._print_watch):
                    continue
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
            await send_pacer.wait()
            async with gw._send_lock:
                await ws_send(ws, {"type": "subscribe", "channel": f"trade/{mi}"})
                gw._trade_subs.add(mi)
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
    if msg.get("error") or msg.get("type") == "error":
        logger.warning("market ws error: %s", msg.get("error") or msg)
        return
    action, kind = split_ws_type(msg.get("type"))
    if kind == "order_book":
        await gw._books.handle_message(msg)
    elif kind == "trade":
        # Official UI uses trade_fe; public JSON still uses trade. Both map here.
        await handle_trades(gw, msg, snapshot=action == "subscribed")
    elif kind == "candle":
        await handle_candle(gw, msg)
    elif kind == "market_stats":
        await gw.apply_market_stats(msg)


def _account_index(raw: Any) -> int:
    try:
        n = int(raw or 0)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


async def handle_trades(gw: LighterGateway, msg: dict[str, Any], *, snapshot: bool = False) -> None:
    market_index = message_market_index(msg, "trade")
    if market_index is None:
        return

    trades_raw = msg.get("trades") or msg.get("trade") or []
    if isinstance(trades_raw, dict):
        trades_raw = [trades_raw]

    liq_kinds = LiquidationFeed.liq_kinds()
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
            snapshot=snapshot,
        )

    if not snapshot and market_index in gw._print_watch:
        prints = [
            t
            for t in trades_raw
            if isinstance(t, dict) and str(t.get("type") or "trade") not in liq_kinds
        ]
        prints.sort(key=lambda t: int(t.get("timestamp", t.get("time", 0)) or 0))
        prices = [str(t.get("price")) for t in prints if t.get("price") not in (None, "")]
        if prices:
            # Trail F9: every print, for the desk only; the web has its own tape.
            gw.emit_internal({"type": "prints", "market_index": market_index, "prices": prices})

    if market_index != gw._current_market_index:
        return

    # Fan-out prepends; a late subscribed/* dump must not clobber live prints.
    if snapshot and gw._recent_trades.get(market_index):
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
            side=taker_side(t),
            timestamp=int(t.get("timestamp", t.get("time", 0))),
            tx_hash=str(t.get("tx_hash") or ""),
            bid_account_id=_account_index(t.get("bid_account_id")),
            ask_account_id=_account_index(t.get("ask_account_id")),
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


_MAX_MINUTE_CANDLES = 2000


def _ws_candle(raw: Any) -> dict[str, float | int] | None:
    if not isinstance(raw, dict):
        return None
    try:
        t = int(raw.get("timestamp", raw.get("t", 0)) or 0)
        if t > 1e12:
            t //= 1000
        if t <= 0:
            return None
        t = (t // 60) * 60
        return {
            "time": t,
            "open": float(raw.get("open", raw.get("o", 0))),
            "high": float(raw.get("high", raw.get("h", 0))),
            "low": float(raw.get("low", raw.get("l", 0))),
            "close": float(raw.get("close", raw.get("c", 0))),
            "volume": float(raw.get("volume", raw.get("v", 0))),
        }
    except (TypeError, ValueError):
        return None


async def handle_candle(gw: LighterGateway, msg: dict[str, Any]) -> None:
    market_index = parse_channel_market(msg.get("channel"), "candle")
    if market_index is None:
        return

    candles_raw = msg.get("candles") or []
    if not candles_raw and "candlestick" in msg:
        candles_raw = [msg.get("candlestick")]
    seen: dict[int, dict[str, float | int]] = {}
    for raw in candles_raw:
        bar = _ws_candle(raw)
        if bar is None:
            continue
        seen[int(bar["time"])] = bar
    parsed = sorted(seen.values(), key=lambda b: int(b["time"]))
    if not parsed:
        return
    parsed = parsed[-_MAX_MINUTE_CANDLES:]
    resolution = candle_channel_resolution(msg.get("channel"))
    if resolution is not None:
        await gw.on_tone_candles(market_index, resolution, parsed)
    if market_index != gw._current_market_index or resolution not in (None, "1m"):
        return
    action, _ = split_ws_type(msg.get("type"))
    # subscribed/* replaces; update/* merges. Typeless frames keep the old
    # length heuristic (1–2 bars = forming/rollover upsert).
    if action == "subscribed":
        snapshot = True
    elif action == "update":
        snapshot = False
    else:
        snapshot = len(parsed) > 2
    if snapshot:
        gw.broadcast({"type": "candles", "market_index": market_index, "candles": parsed})
        return
    payload: dict[str, Any] = {"type": "candle", "market_index": market_index}
    if len(parsed) == 1:
        payload["candle"] = parsed[0]
    else:
        payload["candles"] = parsed
    gw.broadcast(payload)


async def run_tone_ws(gw: LighterGateway) -> None:
    """Candle closes for tone alerts. One connection per 450 channels."""
    while True:
        epoch = gw._tone_epoch
        try:
            await _tone_session(gw, epoch)
        except asyncio.CancelledError:
            break
        except Exception as e:
            _log_ws_error(e, "tone ws error, reconnecting in 3s")
            await asyncio.sleep(3)
        if gw._tone_epoch == epoch:
            gw._request_tone_fill("stale")


async def _tone_session(gw: LighterGateway, epoch: int) -> None:
    channels = gw.tone_channels()
    if not channels:
        await asyncio.sleep(5)
        return
    groups = [channels[i : i + _TONE_CONN_CAP] for i in range(0, len(channels), _TONE_CONN_CAP)]
    tasks = [asyncio.create_task(_tone_conn(gw, epoch, group)) for group in groups]
    try:
        done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            exc = task.exception()
            if exc is not None:
                raise exc
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task


async def _tone_subscribe(gw: LighterGateway, epoch: int, ws: Any, channels: list[str]) -> None:
    for channel in channels:
        if gw._tone_epoch != epoch:
            return
        await send_pacer.wait()
        await ws_send(ws, {"type": "subscribe", "channel": channel})


async def _tone_conn(gw: LighterGateway, epoch: int, channels: list[str]) -> None:
    async with websockets.connect(settings.ws_url) as ws:
        # Read while subscribing: paced subs take minutes, and unread snapshots stall keepalive pongs.
        side = [
            asyncio.create_task(_tone_subscribe(gw, epoch, ws, channels)),
            asyncio.create_task(_tone_ping(ws)),
        ]
        try:
            last = time.monotonic()
            while gw._tone_epoch == epoch:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=5)
                except TimeoutError:
                    if time.monotonic() - last >= _SILENCE_S:
                        logger.warning("tone ws silent — reconnecting")
                        return
                    continue
                last = time.monotonic()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                kind = msg.get("type")
                if kind == "ping":
                    await ws_send(ws, {"type": "pong"})
                    continue
                if kind == "pong":
                    continue
                if msg.get("error") or kind == "error":
                    logger.warning("tone ws error: %s", msg.get("error") or msg)
                    continue
                await _apply_tone_candles(gw, msg)
        finally:
            for task in side:
                task.cancel()
            for task in side:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task


async def _tone_ping(ws: Any) -> None:
    while True:
        await asyncio.sleep(_PING_EVERY)
        await ws_send(ws, {"type": "ping"})


async def _apply_tone_candles(gw: LighterGateway, msg: dict[str, Any]) -> None:
    resolution = candle_channel_resolution(msg.get("channel"))
    market_index = parse_channel_market(msg.get("channel"), "candle")
    if resolution is None or market_index is None:
        return
    raw_rows = msg.get("candles") or []
    if not raw_rows and msg.get("candlestick"):
        raw_rows = [msg["candlestick"]]
    bars: list[dict[str, float | int]] = []
    for raw in raw_rows:
        bar = _ws_candle(raw)
        if bar is not None:
            bars.append(bar)
    if bars:
        await gw.on_tone_candles(market_index, resolution, bars)
