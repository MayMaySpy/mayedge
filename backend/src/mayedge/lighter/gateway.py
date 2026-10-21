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
from mayedge.alerts import AlertDetector
from mayedge.config import settings
from mayedge.lighter.budget import budget
from mayedge.lighter.gateway_boards import GatewayBoards
from mayedge.lighter.liquidations import LiquidationFeed
from mayedge.lighter.market_ws import run_tone_ws, run_ws_loop, ws_send
from mayedge.lighter.models import (
    Candle,
    MarketMeta,
    Trade,
    normalize_market_type,
    open_interest_usd,
    to_float,
)
from mayedge.lighter.order_book import OrderBookFeed
from mayedge.persist_funding import funding_print_rows, funding_sample_rows
from mayedge.persist_oi import open_interest_sample_rows
from mayedge.tone_alerts import ToneBook
from mayedge.tone_timeframes import (
    load_tone_timeframes,
)

logger = logging.getLogger(__name__)


def _detail_field(obj: Any, *names: str) -> Any:
    extra = getattr(obj, "additional_properties", None)
    for name in names:
        val = getattr(obj, name, None)
        if val is not None:
            return val
        if isinstance(extra, dict) and extra.get(name) is not None:
            return extra[name]
    return None


_HEALTH_DEGRADED_S = 10.0
_MARKET_REFRESH_S = 3600.0
_REST_CANDLE_CAP = 500


class LighterGateway(GatewayBoards):
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
        self._oi_task: asyncio.Task[None] | None = None
        self._ws_connected = asyncio.Event()
        self._subscribers: list[Callable[[dict[str, Any]], None]] = []
        # Desk-only messages (Trail prints). Never sent to the web.
        self._internal: list[Callable[[dict[str, Any]], None]] = []
        # Markets whose every trade print the desk keeps (Trail F9), on screen or not.
        self._print_watch: set[int] = set()
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
        self._alerts = AlertDetector(self.broadcast, held=self._held_markets)
        self._tone_book = ToneBook()
        self._tone_resync = asyncio.Event()
        self._tone_generation = 0
        self._tone_task: asyncio.Task[None] | None = None
        self._tone_ws_task: asyncio.Task[None] | None = None
        self._market_task: asyncio.Task[None] | None = None
        self._tone_fill = ""
        self._tone_epoch = 0
        self._alert_minute_task: asyncio.Task[None] | None = None
        self._funding_backfill_task: asyncio.Task[None] | None = None
        self._scan_task: asyncio.Task[None] | None = None
        self._last_scan: dict[str, str] = {}
        self._skipped_markets = ""

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
        try:
            self._seed_alert_levels()
        except Exception:
            logger.exception("failed to load stored funding and open interest")
        try:
            await asyncio.to_thread(store.fold_open_interest, now_ms=int(time.time() * 1000))
        except Exception:
            logger.exception("failed to fold open interest")
        self._ws_task = asyncio.create_task(run_ws_loop(self))
        self._health_task = asyncio.create_task(self._health_loop())
        self._oi_task = asyncio.create_task(self._oi_sample_loop())
        self._market_task = asyncio.create_task(self._market_refresh_loop())
        self._tone_book.set_timeframes(load_tone_timeframes())
        self._tone_generation += 1
        self._tone_fill = "full"
        self._tone_resync.set()
        self._tone_task = asyncio.create_task(self._tone_loop())
        self._tone_ws_task = asyncio.create_task(run_tone_ws(self))
        self._alert_minute_task = asyncio.create_task(self._alert_minute_backfill_loop())
        self._funding_backfill_task = asyncio.create_task(self._funding_backfill_loop())
        self._scan_task = asyncio.create_task(self._scan_loop())

    async def stop(self) -> None:
        for task in (
            self._ws_task,
            self._health_task,
            self._oi_task,
            self._tone_task,
            self._tone_ws_task,
            self._market_task,
            self._alert_minute_task,
            self._funding_backfill_task,
            self._scan_task,
        ):
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._ws_task = None
        self._health_task = None
        self._oi_task = None
        self._tone_task = None
        self._tone_ws_task = None
        self._market_task = None
        self._alert_minute_task = None
        self._funding_backfill_task = None
        self._scan_task = None
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

    def subscribe_internal(self, callback: Callable[[dict[str, Any]], None]) -> None:
        if callback not in self._internal:
            self._internal.append(callback)

    def emit_internal(self, message: dict[str, Any]) -> None:
        for cb in list(self._internal):
            try:
                cb(message)
            except Exception:
                logger.exception("internal subscriber error")

    def watch_prints(self, market_index: int, on: bool) -> None:
        """Keep, or stop keeping, every trade print on a Market (Trail F9)."""
        if on:
            self._print_watch.add(market_index)
        else:
            self._print_watch.discard(market_index)

    @property
    def client(self) -> lighter.ApiClient:
        if not self._client:
            raise RuntimeError("Gateway not started")
        return self._client

    async def _load_markets(self) -> None:
        await budget.take("background", wait=True)
        order_api = lighter.OrderApi(self.client)
        detail_resp = await order_api.order_book_details()
        rows = list(getattr(detail_resp, "order_book_details", None) or [])
        rows.extend(getattr(detail_resp, "spot_order_book_details", None) or [])
        seen: set[int] = set()
        skipped: list[str] = []
        self._symbol_to_index.clear()
        self._perp_by_symbol.clear()
        self._spot_by_symbol.clear()
        for book in rows:
            status = str(_detail_field(book, "status") or "").lower()
            if status and status != "active":
                continue
            idx = int(book.market_id)
            symbol = str(getattr(book, "symbol", None) or f"M{idx}")
            raw_type = _detail_field(book, "market_type")
            if normalize_market_type(raw_type) == "other":
                skipped.append(f"{symbol} ({raw_type})")
                continue
            price_dec = _detail_field(book, "price_decimals", "supported_price_decimals")
            size_dec = _detail_field(book, "size_decimals", "supported_size_decimals")
            last = to_float(_detail_field(book, "last_trade_price"))
            mark = to_float(_detail_field(book, "mark_price")) or last
            meta = self._markets.get(idx) or MarketMeta(
                market_index=idx,
                symbol=symbol,
                price_decimals=2 if price_dec is None else int(price_dec),
                size_decimals=4 if size_dec is None else int(size_dec),
                min_base_amount=0.0,
                min_quote_amount=0.0,
            )
            meta.symbol = symbol
            meta.price_decimals = 2 if price_dec is None else int(price_dec)
            meta.size_decimals = 4 if size_dec is None else int(size_dec)
            meta.min_base_amount = to_float(_detail_field(book, "min_base_amount"))
            meta.min_quote_amount = to_float(_detail_field(book, "min_quote_amount"))
            meta.market_type = normalize_market_type(_detail_field(book, "market_type"))
            if mark:
                meta.mark_price = mark
            meta.last_trade_price = last or meta.last_trade_price
            config = getattr(book, "market_config", None)
            index = to_float(_detail_field(book, "index_price"))
            if not index and config is not None:
                index = to_float(getattr(config, "index_price", None))
            if index:
                meta.index_price = index
            meta.volume_24h = to_float(_detail_field(book, "daily_quote_token_volume"))
            raw_oi = _detail_field(book, "open_interest")
            if raw_oi is not None and mark:
                meta.open_interest = open_interest_usd(to_float(raw_oi) * mark)
            change = _detail_field(book, "daily_price_change")
            meta.change_24h = None if change is None else to_float(change)
            min_imf = int(_detail_field(book, "min_initial_margin_fraction") or 0)
            default_imf = int(_detail_field(book, "default_initial_margin_fraction") or 0)
            maintenance = int(_detail_field(book, "maintenance_margin_fraction") or 0)
            if min_imf > 0:
                meta.min_initial_margin_fraction = min_imf
            if default_imf > 0:
                meta.default_initial_margin_fraction = default_imf
            if maintenance > 0:
                meta.maintenance_margin_fraction = maintenance
            self._markets[idx] = meta
            seen.add(idx)
            key = symbol.upper()
            if meta.is_perp:
                self._perp_by_symbol[key] = idx
                self._symbol_to_index[key] = idx
            else:
                self._spot_by_symbol[key] = idx
                self._symbol_to_index.setdefault(key, idx)
        for idx in list(self._markets):
            if idx not in seen:
                del self._markets[idx]
        text = ", ".join(skipped)
        if text and text != self._skipped_markets:
            logger.info("skipped markets: %s", text)
        self._skipped_markets = text

    async def _market_refresh_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(_MARKET_REFRESH_S)
                await self._load_markets()
                self._refresh_trade_targets()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("market refresh failed")

    def _stat_rows(self, msg: dict[str, Any]) -> list[dict[str, Any]] | None:
        stats_blob = msg.get("market_stats")
        if not isinstance(stats_blob, dict) or not stats_blob:
            return None
        if "market_id" in stats_blob or "symbol" in stats_blob:
            return [stats_blob]
        return [row for row in stats_blob.values() if isinstance(row, dict)]

    def _apply_stat_row(self, row: dict[str, Any]) -> MarketMeta | None:
        mi = row.get("market_id")
        if mi is None:
            return None
        try:
            idx = int(mi)
        except (TypeError, ValueError):
            return None
        meta = self._markets.get(idx)
        if not meta:
            return None
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
        settled = row.get("funding_rate")
        if settled is not None:
            meta.settled_funding_rate = to_float(settled)
        fr = row.get("current_funding_rate")
        if fr is None:
            fr = settled
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
        self._alerts.on_market_stats(meta)
        if meta.quote_key() != before:
            return meta
        return None

    def _finish_market_stats(self, dirty: list[MarketMeta]) -> None:
        if dirty:
            self.broadcast({"type": "market_stats", "markets": [m.as_quote_dict() for m in dirty]})
        self._alerts.flush()
        from mayedge.lighter.account import account_service

        account_service.touch_marks()

    def _apply_market_stats(self, msg: dict[str, Any]) -> None:
        rows = self._stat_rows(msg)
        if rows is None:
            return
        dirty: list[MarketMeta] = []
        for row in rows:
            meta = self._apply_stat_row(row)
            if meta is not None:
                dirty.append(meta)
        self._finish_market_stats(dirty)

    async def apply_market_stats(self, msg: dict[str, Any]) -> None:
        """One market, then the loop. A full stats wave must not be one callback."""
        rows = self._stat_rows(msg)
        if rows is None:
            return
        dirty: list[MarketMeta] = []
        for row in rows:
            meta = self._apply_stat_row(row)
            if meta is not None:
                dirty.append(meta)
            await self._breathe()
        self._finish_market_stats(dirty)

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
        *,
        lane: str = "read",
        end_ms: int | None = None,
    ) -> list[Candle]:
        if resolution == "1s":
            series = self._candles_1s.get(market_index)
            if not series:
                series = self._rebuild_1s(market_index)
            return list(series[-count:])

        count = min(max(int(count), 1), _REST_CANDLE_CAP)
        await budget.take(lane, wait=lane == "background")
        candle_api = lighter.CandlestickApi(self.client)
        end = end_ms if end_ms is not None else int(time.time()) * 1000
        resolution_seconds = {
            "1m": 60,
            "5m": 300,
            "15m": 900,
            "30m": 1800,
            "1h": 3600,
            "4h": 14400,
            "12h": 43200,
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
                        self._books.invalidate(prev)
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

    async def _oi_sample_loop(self) -> None:
        """Write the open interest held at each UTC minute close. Missed minutes stay gaps."""
        while True:
            try:
                now = time.time()
                delay = (int(now) // 60 + 1) * 60 - now + 0.25
                await asyncio.sleep(max(0.25, delay))
                self._flush_open_interest()
                await asyncio.to_thread(store.fold_open_interest_if_due)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("open interest sample failed")
                await asyncio.sleep(5)

    def _flush_open_interest(self) -> None:
        closed = int(time.time()) // 60 - 1
        if closed < 0:
            return
        # Funding is written beside open interest, so a restart knows what is normal.
        funding = funding_sample_rows(self._markets.values())
        if funding:
            keep = self._alerts.settings.funding_retention_days * 1440
            store.flush_funding(funding, minute_index=closed, keep_minutes=keep)
        prints = funding_print_rows(self._markets.values())
        if prints:
            store.flush_funding_prints(prints)
        rows = open_interest_sample_rows(self._markets.values())
        if not rows:
            return
        store.flush_open_interest(rows, minute_index=closed)

    def _seed_alert_levels(self) -> None:
        """Give the alert rules the hour of open interest and the day of funding before this run."""
        minute = int(time.time()) // 60
        cfg = self._alerts.settings
        self._alerts.seed_levels("funding", store.recent_funding(minute - cfg.level_window_min))
        self._alerts.seed_levels(
            "oi", store.recent_open_interest(minute - cfg.spike_window_min - 2)
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
        if mi is None:
            return
        self._books.invalidate(mi)
        if self._ws is None:
            logger.warning("resync_book skipped; no ws market=%s", mi)
            return
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
        return self._books.is_synced(market_index)

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
        self._books.invalidate(market_index)
        try:
            async with self._send_lock:
                with contextlib.suppress(Exception):
                    await ws_send(
                        ws, {"type": "unsubscribe", "channel": f"order_book/{market_index}"}
                    )
                await ws_send(ws, {"type": "subscribe", "channel": f"order_book/{market_index}"})
        except Exception:
            logger.exception("re-subscribe order_book/%s failed", market_index)

    def trades_payload(
        self, market_index: int, trades: list[Trade] | None = None
    ) -> dict[str, Any] | None:
        rows = trades if trades is not None else self._recent_trades.get(market_index, [])
        if not rows:
            return None
        out: list[dict[str, Any]] = []
        for t in rows:
            row: dict[str, Any] = {
                "price": t.price,
                "size": t.size,
                "side": t.side,
                "timestamp": t.timestamp,
            }
            if t.tx_hash:
                row["tx_hash"] = t.tx_hash
            if t.bid_account_id:
                row["bid_account_id"] = t.bid_account_id
            if t.ask_account_id:
                row["ask_account_id"] = t.ask_account_id
            out.append(row)
        return {
            "type": "trades",
            "market_index": market_index,
            "trades": out,
        }

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
