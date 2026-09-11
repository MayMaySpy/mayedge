from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from typing import Any

import lighter
from lighter.configuration import Configuration

from mayedge import db as store
from mayedge import feed_health
from mayedge.alerts import ExploitDetector
from mayedge.config import settings
from mayedge.lighter.liquidations import LiquidationFeed
from mayedge.lighter.market_ws import run_ws_loop, ws_send
from mayedge.lighter.models import (
    Candle,
    MarketMeta,
    Trade,
    normalize_market_type,
    open_interest_usd,
    to_float,
)
from mayedge.lighter.order_book import OrderBookFeed

logger = logging.getLogger(__name__)

_HEALTH_DEGRADED_S = 10.0


class LighterGateway:
    """REST + exchange websocket gateway to Lighter."""

    def __init__(self) -> None:
        self._client: lighter.ApiClient | None = None
        self._markets: dict[int, MarketMeta] = {}
        self._symbol_to_index: dict[str, int] = {}
        self._perp_by_symbol: dict[str, int] = {}
        self._spot_by_symbol: dict[str, int] = {}
        self._pinned_books: set[int] = set()
        self._ws_task: asyncio.Task[None] | None = None
        self._health_task: asyncio.Task[None] | None = None
        self._ws_connected = asyncio.Event()
        self._subscribers: list[Callable[[dict[str, Any]], None]] = []
        self._current_market_index: int | None = None
        self._recent_trades: dict[int, list[Trade]] = {}
        self._candles_1s: dict[int, list[Candle]] = {}
        self._lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        self._focus_gate = asyncio.Event()
        self._focus_gate.set()
        self._max_1s = 3600
        self._ws: Any | None = None
        self._trade_subs: set[int] = set()
        self._trade_subs_target: set[int] = set()
        self._last_msg_at = 0.0
        self._books = OrderBookFeed(self.broadcast, resubscribe=self._resubscribe_order_book_sync)
        self._liqs = LiquidationFeed(self.broadcast)
        self._alerts = ExploitDetector(self.broadcast)

    async def start(self) -> None:
        self._client = lighter.ApiClient(Configuration(host=settings.base_url))
        store.init_db()
        self._liqs.hydrate()
        await self._load_markets()
        if self._current_market_index is None:
            default = self.get_market(settings.default_market_symbol)
            if default:
                self._current_market_index = default.market_index
            elif self._markets:
                self._current_market_index = next(iter(self._markets))
        self._refresh_trade_targets()
        self._books.set_current_market(self._current_market_index)
        self._books.start_resync_loop(lambda: self._current_market_index)
        self._ws_task = asyncio.create_task(run_ws_loop(self))
        self._health_task = asyncio.create_task(self._health_loop())

    async def stop(self) -> None:
        for task in (self._ws_task, self._health_task):
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._ws_task = None
        self._health_task = None
        await self._books.stop_resync_loop()
        if self._client:
            await self._client.close()
            self._client = None

    def subscribe(self, callback: Callable[[dict[str, Any]], None]) -> None:
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[dict[str, Any]], None]) -> None:
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def _broadcast(self, message: dict[str, Any]) -> None:
        if message.get("type") == "liquidations":
            self._alerts.on_liquidations(message.get("items") or [])
        for cb in list(self._subscribers):
            try:
                cb(message)
            except Exception:
                logger.exception("subscriber error")

    def broadcast(self, message: dict[str, Any]) -> None:
        self._broadcast(message)

    @property
    def client(self) -> lighter.ApiClient:
        if not self._client:
            raise RuntimeError("Gateway not started")
        return self._client

    async def _load_markets(self) -> None:
        order_api = lighter.OrderApi(self.client)
        details = await order_api.order_books()
        self._markets.clear()
        self._symbol_to_index.clear()
        self._perp_by_symbol.clear()
        self._spot_by_symbol.clear()
        for book in details.order_books or []:
            symbol = getattr(book, "symbol", None) or f"M{book.market_id}"
            meta = MarketMeta(
                market_index=book.market_id,
                symbol=symbol,
                price_decimals=getattr(book, "supported_price_decimals", 2) or 2,
                size_decimals=getattr(book, "supported_size_decimals", 4) or 4,
                min_base_amount=to_float(getattr(book, "min_base_amount", 0)),
                min_quote_amount=to_float(getattr(book, "min_quote_amount", 0)),
                market_type=normalize_market_type(getattr(book, "market_type", None)),
            )
            self._markets[meta.market_index] = meta
            key = symbol.upper()
            if meta.is_perp:
                self._perp_by_symbol[key] = meta.market_index
                self._symbol_to_index[key] = meta.market_index
            else:
                self._spot_by_symbol[key] = meta.market_index
                self._symbol_to_index.setdefault(key, meta.market_index)

        try:
            detail_resp = await order_api.order_book_details()
            for d in detail_resp.order_book_details or []:
                idx = d.market_id
                if idx in self._markets:
                    last = to_float(getattr(d, "last_trade_price", None))
                    mark = to_float(getattr(d, "mark_price", None)) or last
                    self._markets[idx].mark_price = mark
                    self._markets[idx].index_price = to_float(
                        getattr(d, "market_config", None)
                        and getattr(d.market_config, "index_price", None)
                    )
                    self._markets[idx].last_trade_price = last
                    self._markets[idx].volume_24h = to_float(
                        getattr(d, "daily_quote_token_volume", None)
                    )
                    raw_oi = getattr(d, "open_interest", None)
                    if raw_oi is not None and mark:
                        # REST OI is base size; convert to two-sided quote notional.
                        self._markets[idx].open_interest = open_interest_usd(
                            to_float(raw_oi) * mark
                        )
                    change = getattr(d, "daily_price_change", None)
                    self._markets[idx].change_24h = None if change is None else to_float(change)
                    min_imf = int(getattr(d, "min_initial_margin_fraction", 0) or 0)
                    default_imf = int(getattr(d, "default_initial_margin_fraction", 0) or 0)
                    if min_imf > 0:
                        self._markets[idx].min_initial_margin_fraction = min_imf
                    if default_imf > 0:
                        self._markets[idx].default_initial_margin_fraction = default_imf
        except Exception:
            logger.exception("failed to load order book details")

    def _apply_market_stats(self, msg: dict[str, Any]) -> None:
        stats_blob = msg.get("market_stats")
        if not stats_blob:
            return
        rows: list[Any]
        if isinstance(stats_blob, dict):
            if "market_id" in stats_blob or "symbol" in stats_blob:
                rows = [stats_blob]
            else:
                rows = list(stats_blob.values())
        else:
            return
        dirty: list[MarketMeta] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            mi = row.get("market_id")
            if mi is None:
                continue
            try:
                idx = int(mi)
            except (TypeError, ValueError):
                continue
            meta = self._markets.get(idx)
            if not meta:
                continue
            before = meta.quote_key()
            mark = to_float(row.get("mark_price"))
            last = to_float(row.get("last_trade_price"))
            if mark:
                meta.mark_price = mark
            if last:
                meta.last_trade_price = last
            vol = row.get("daily_quote_token_volume")
            if vol is not None:
                meta.volume_24h = to_float(vol)
            change = row.get("daily_price_change")
            if change is not None:
                meta.change_24h = to_float(change)
            idx_px = to_float(row.get("index_price"))
            if idx_px:
                meta.index_price = idx_px
            # Wire units are percent (0.0012 = 0.0012%/hr). Prefer the upcoming
            # estimate; funding_rate is the last settled print.
            fr = row.get("current_funding_rate")
            if fr is None:
                fr = row.get("funding_rate")
            if fr is not None:
                meta.funding_rate = to_float(fr)
            oi = row.get("open_interest")
            if oi is not None:
                # WS OI is already one-sided quote notional.
                meta.open_interest = open_interest_usd(to_float(oi))
            oi_lim = row.get("open_interest_limit")
            if oi_lim is not None:
                meta.open_interest_limit = to_float(oi_lim)
            bid = to_float(row.get("best_bid_price"))
            if bid:
                meta.best_bid_price = bid
            ask = to_float(row.get("best_ask_price"))
            if ask:
                meta.best_ask_price = ask
            mid = to_float(row.get("mid_price"))
            if mid:
                meta.mid_price = mid
            prem = row.get("premium")
            if prem is not None:
                meta.premium = to_float(prem)
            fts = row.get("funding_timestamp")
            if fts is not None:
                try:
                    meta.funding_timestamp = int(fts)
                except (TypeError, ValueError):
                    pass
            hi = row.get("daily_price_high")
            if hi is not None:
                meta.daily_price_high = to_float(hi)
            lo = row.get("daily_price_low")
            if lo is not None:
                meta.daily_price_low = to_float(lo)
            base_vol = row.get("daily_base_token_volume")
            if base_vol is not None:
                meta.volume_base_24h = to_float(base_vol)
            if meta.quote_key() != before:
                dirty.append(meta)
            self._alerts.on_market_stats(meta)
        if dirty:
            self.broadcast({"type": "market_stats", "markets": [m.as_quote_dict() for m in dirty]})
        self._alerts.flush()
        from mayedge.lighter.account import account_service

        account_service.touch_marks()

    def list_markets(self) -> list[MarketMeta]:
        return list(self._markets.values())

    def get_market(self, symbol: str) -> MarketMeta | None:
        key = symbol.upper()
        idx = self._perp_by_symbol.get(key)
        if idx is None:
            idx = self._symbol_to_index.get(key)
        if idx is None:
            return None
        return self._markets.get(idx)

    def get_market_by_index(self, market_index: int) -> MarketMeta | None:
        return self._markets.get(market_index)

    def resolve_market_index(self, symbol: str) -> int:
        meta = self.get_market(symbol)
        if meta:
            return meta.market_index
        raise ValueError(f"Unknown market symbol: {symbol}")

    def resolve_subscribe_market(self, symbol: str, market_index: Any | None = None) -> int:
        """Desk subscribe: perp for the symbol. Ignore an index that belongs to another pair."""
        wanted = self.get_market(symbol)
        if market_index is not None and market_index != "":
            try:
                idx = int(market_index)
            except (TypeError, ValueError):
                idx = None
            else:
                meta = self._markets.get(idx)
                if meta is not None and meta.symbol.upper() == str(symbol).upper():
                    if wanted is not None and wanted.is_perp and not meta.is_perp:
                        return wanted.market_index
                    return idx
        if wanted:
            return wanted.market_index
        return self.resolve_market_index(symbol)

    async def get_candles(
        self,
        market_index: int,
        resolution: str = "1m",
        count: int = 500,
    ) -> list[Candle]:
        if resolution == "1s":
            series = self._candles_1s.get(market_index)
            if not series:
                series = self._rebuild_1s(market_index)
            return list(series[-count:])

        candle_api = lighter.CandlestickApi(self.client)
        end = int(time.time()) * 1000
        resolution_seconds = {
            "1m": 60,
            "5m": 300,
            "15m": 900,
            "1h": 3600,
            "4h": 14400,
            "1d": 86400,
        }
        step = resolution_seconds.get(resolution, 60)
        start = end - step * count * 1000
        resp = await candle_api.candles(
            market_id=market_index,
            resolution=resolution,
            start_timestamp=start,
            end_timestamp=end,
            count_back=count,
        )
        candles: list[Candle] = []
        for c in resp.c or []:
            candles.append(
                Candle(
                    time=int(c.t // 1000 if c.t > 1e12 else c.t),
                    open=float(c.o),
                    high=float(c.h),
                    low=float(c.l),
                    close=float(c.c),
                    volume=float(c.v or 0),
                )
            )
        by_t = {c.time: c for c in candles}
        return sorted(by_t.values(), key=lambda x: x.time)

    def bind_market_ws(self, ws: Any) -> int:
        """Attach the exchange socket; return the market this session must subscribe."""
        market_index = self._current_market_index
        if market_index is None:
            default = self.get_market(settings.default_market_symbol)
            market_index = default.market_index if default else next(iter(self._markets))
            self._current_market_index = market_index
        self._books.set_current_market(market_index)
        self._ws = ws
        self._ws_connected.set()
        return market_index

    def unbind_market_ws(self) -> None:
        self._ws = None
        self._ws_connected.clear()

    async def set_active_market(self, market_index: int) -> None:
        async with self._lock:
            prev = self._current_market_index
            same = prev == market_index
            if same:
                self._books.set_current_market(market_index)
                if self._ws is None or self._books.has_book(market_index):
                    return
            else:
                self._current_market_index = market_index
                self._books.set_current_market(market_index)
                self._books.clear_pending()
                self._prune_trade_buffers(keep=market_index)

        ws = self._ws
        if ws is not None:
            self._focus_gate.clear()
            try:
                async with self._send_lock:
                    if not same and prev is not None and prev not in self._pinned_books:
                        await ws_send(ws, {"type": "unsubscribe", "channel": f"order_book/{prev}"})
                        await ws_send(ws, {"type": "unsubscribe", "channel": f"candle/{prev}/1m"})
                    await ws_send(
                        ws, {"type": "subscribe", "channel": f"order_book/{market_index}"}
                    )
                    await ws_send(ws, {"type": "subscribe", "channel": f"candle/{market_index}/1m"})
                    if market_index not in self._trade_subs:
                        await ws_send(ws, {"type": "subscribe", "channel": f"trade/{market_index}"})
                        self._trade_subs.add(market_index)
                    self._trade_subs_target.add(market_index)
            except Exception:
                logger.exception("in-place market switch failed; reconnecting")
                with contextlib.suppress(Exception):
                    await ws.close()
                self.unbind_market_ws()
            finally:
                self._focus_gate.set()

        if not same:
            self.broadcast({"type": "market_switch", "market_index": market_index})

    async def wait_for_book(self, market_index: int) -> bool:
        if not self._books.has_book(market_index):
            await self._ws_connected.wait()
        while not self._books.has_book(market_index):
            await asyncio.sleep(0.03)
        return True

    def _refresh_trade_targets(self) -> None:
        targets = {m.market_index for m in self._markets.values() if m.is_perp}
        self._trade_subs_target = targets
        feed_health.set_market_ws(
            "reconnecting" if not self._ws else "live",
            trade_subs=len(self._trade_subs),
            trade_subs_target=len(targets),
            broadcast=False,
        )

    async def _health_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(_HEALTH_DEGRADED_S)
                snap = feed_health.snapshot()
                if snap.get("market_ws") != "live" or snap.get("account_ws") not in (
                    "live",
                    "down",
                ):
                    self.broadcast(snap)
                elif snap.get("market_ws") == "live":
                    feed_health.set_market_ws(
                        "live",
                        trade_subs=len(self._trade_subs),
                        trade_subs_target=len(self._trade_subs_target),
                        broadcast=False,
                    )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("health loop error")

    def order_book_payload(
        self, market_index: int, *, bump_seq: bool = False
    ) -> dict[str, Any] | None:
        return self._books.order_book_payload(market_index, bump_seq=bump_seq)

    def best_bid_ask(self, market_index: int) -> tuple[str | None, str | None]:
        return self._books.best_bid_ask(market_index)

    def request_book_snapshot(self, market_index: int | None = None) -> None:
        mi = market_index if market_index is not None else self._current_market_index
        self._books.request_snapshot(mi)
        if mi is None or self._books.has_book(mi):
            return
        if self._ws is None:
            logger.warning("resync_book skipped; no ws and no local book market=%s", mi)
            return
        logger.info("resync_book: re-subscribe order_book/%s (no local snapshot)", mi)
        asyncio.create_task(self._resubscribe_order_book(mi))

    def _resubscribe_order_book_sync(self, market_index: int) -> None:
        asyncio.create_task(self._resubscribe_order_book(market_index))

    def is_book_synced(self, market_index: int) -> bool:
        return self._books.is_synced(market_index)

    async def ensure_order_book(self, market_index: int, *, timeout_s: float = 3.0) -> bool:
        self._pinned_books.add(market_index)
        self._books.pin(market_index)
        if self._books.is_synced(market_index):
            return True
        await self._resubscribe_order_book(market_index)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self._books.is_synced(market_index):
                return True
            await asyncio.sleep(0.03)
        return self._books.has_book(market_index)

    def release_order_book(self, market_index: int) -> None:
        self._pinned_books.discard(market_index)
        self._books.unpin(market_index)
        if market_index == self._current_market_index:
            return
        asyncio.create_task(self._unsubscribe_order_book(market_index))

    async def _unsubscribe_order_book(self, market_index: int) -> None:
        ws = self._ws
        if ws is None:
            return
        try:
            async with self._send_lock:
                await ws_send(ws, {"type": "unsubscribe", "channel": f"order_book/{market_index}"})
        except Exception:
            logger.exception("unsubscribe order_book/%s failed", market_index)

    async def _resubscribe_order_book(self, market_index: int) -> None:
        ws = self._ws
        if ws is None:
            return
        try:
            async with self._send_lock:
                await ws_send(ws, {"type": "subscribe", "channel": f"order_book/{market_index}"})
        except Exception:
            logger.exception("re-subscribe order_book/%s failed", market_index)

    def trades_payload(
        self, market_index: int, trades: list[Trade] | None = None
    ) -> dict[str, Any] | None:
        rows = trades if trades is not None else self._recent_trades.get(market_index, [])
        if not rows:
            return None
        return {
            "type": "trades",
            "market_index": market_index,
            "trades": [
                {
                    "price": t.price,
                    "size": t.size,
                    "side": t.side,
                    "timestamp": t.timestamp,
                }
                for t in rows
            ],
        }

    def recent_liquidations(self) -> list[dict[str, Any]]:
        return self._liqs.recent()

    def recent_alerts(self) -> list[dict[str, Any]]:
        return self._alerts.recent()

    def _prune_trade_buffers(self, keep: int | None = None) -> None:
        keep_idx = keep if keep is not None else self._current_market_index
        for mi in list(self._recent_trades):
            if mi != keep_idx:
                self._recent_trades.pop(mi, None)
        for mi in list(self._candles_1s):
            if mi != keep_idx:
                self._candles_1s.pop(mi, None)

    @staticmethod
    def _trade_unix(timestamp: int) -> int:
        if timestamp > 1e12:
            return int(timestamp // 1000)
        return int(timestamp)

    def _apply_trade_1s(self, market_index: int, trade: Trade) -> None:
        ts = self._trade_unix(trade.timestamp)
        if ts <= 0:
            return
        try:
            px = float(trade.price)
            sz = float(trade.size or 0)
        except (TypeError, ValueError):
            return
        if px <= 0:
            return
        series = self._candles_1s.setdefault(market_index, [])
        if series and series[-1].time == ts:
            bar = series[-1]
            bar.high = max(bar.high, px)
            bar.low = min(bar.low, px)
            bar.close = px
            bar.volume += sz
        elif not series or ts > series[-1].time:
            series.append(Candle(time=ts, open=px, high=px, low=px, close=px, volume=sz))
            overflow = len(series) - self._max_1s
            if overflow > 0:
                del series[:overflow]

    def _rebuild_1s(self, market_index: int) -> list[Candle]:
        self._candles_1s[market_index] = []
        trades = self._recent_trades.get(market_index, [])
        for trade in reversed(trades):
            self._apply_trade_1s(market_index, trade)
        return self._candles_1s.get(market_index, [])


gateway = LighterGateway()
