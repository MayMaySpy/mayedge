"""The gateway's boards: alerts, liquidations, Scan, Tones and the backfills behind them.

LighterGateway owns the feeds; this half reads them into what Scan and the Alerts panel show.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

import lighter

from mayedge.alerts import AlertDetector, Held
from mayedge.funding_backfill import backfill_funding, backfill_funding_days
from mayedge.lighter.budget import budget
from mayedge.lighter.liquidations import LiquidationFeed
from mayedge.lighter.models import (
    Candle,
    MarketMeta,
    to_float,
)
from mayedge.tone_alerts import ToneBook
from mayedge.tone_timeframes import (
    NATIVE_TONE_TIMEFRAMES,
    TONE_TIMEFRAME_CAP,
    TONE_TIMEFRAME_SECONDS,
    normalize_tone_timeframes,
    save_tone_timeframes,
)

logger = logging.getLogger(__name__)

_TONE_BACKFILL = 500
_ALERT_MINUTE_BARS = 240
_SCAN_BROADCAST_S = 5.0


class GatewayBoards:
    """Mixed into LighterGateway; the fields below are set in its __init__."""

    _alerts: AlertDetector
    _liqs: LiquidationFeed
    _markets: dict[int, MarketMeta]
    _tone_book: ToneBook
    _tone_resync: asyncio.Event
    _tone_generation: int
    _tone_fill: str
    _tone_epoch: int
    _last_scan: dict[str, str]

    def broadcast(self, message: dict[str, Any]) -> None:
        raise NotImplementedError

    @property
    def client(self) -> lighter.ApiClient:
        raise NotImplementedError

    async def get_candles(
        self,
        market_index: int,
        resolution: str = "1m",
        count: int = 500,
        *,
        lane: str = "read",
    ) -> list[Candle]:
        raise NotImplementedError

    def recent_liquidations(self) -> list[dict[str, Any]]:
        return self._liqs.recent()

    def recent_alerts(self) -> list[dict[str, Any]]:
        return self._alerts.recent()

    def alert_stats(self, hours: int = 24, by: str = "rule") -> dict[str, Any]:
        return self._alerts.stats(hours=hours, by=by)

    def alert_whatif(self, *, rule: str, knob: str, value: float, days: int) -> dict[str, Any]:
        return self._alerts.whatif(rule=rule, knob=knob, value=value, days=days)

    def alert_settings(self) -> dict[str, Any]:
        return self._alerts.knob_settings()

    def alert_opened(self, row_id: str) -> bool:
        return self._alerts.opened(row_id)

    def scan_activity(self) -> list[dict[str, Any]]:
        return self._alerts.activity()

    def funding_extremes(self) -> list[dict[str, Any]]:
        return self._alerts.funding_extremes()

    def tone_board(self) -> list[dict[str, Any]]:
        """Liquid perps whose last closed bar on a Tone timeframe is blue or orange."""
        rows = [row for row in self._iter_tone() if row is not None]
        rows.sort(key=lambda row: (-int(row["closed_at"]), str(row["symbol"])))
        return rows

    def _iter_tone(self) -> Iterator[dict[str, Any] | None]:
        for hit in self._tone_book.board():
            if not self._alerts.liquid(hit.market_index):
                yield None
                continue
            meta = self._markets.get(hit.market_index)
            step = TONE_TIMEFRAME_SECONDS[hit.resolution]
            yield {
                "market_index": hit.market_index,
                "symbol": meta.symbol if meta is not None else f"M{hit.market_index}",
                "timeframe": hit.resolution,
                "tone": hit.label.lower(),
                "closed_at": (hit.bar_time + step) * 1000,
                "close": hit.close,
            }

    def _held_markets(self) -> dict[int, Held]:
        """Markets with a Position or a working order, for the alert rules."""
        from mayedge.lighter.account import account_service

        held: dict[int, Held] = {}
        for order in account_service.list_open_orders():
            held.setdefault(order.market_index, Held())
        for pos in account_service.cached_summary().positions:
            if to_float(pos.size) == 0:
                continue
            held[pos.market_index] = Held(
                side=pos.side,
                liquidation_price=to_float(pos.liquidation_price),
            )
        return held

    def tone_timeframes_view(self) -> dict[str, Any]:
        return {
            "timeframes": list(self._tone_book.timeframes),
            "choices": list(NATIVE_TONE_TIMEFRAMES),
            "cap": TONE_TIMEFRAME_CAP,
        }

    def set_tone_timeframes(self, labels: list[str]) -> dict[str, Any]:
        chosen = normalize_tone_timeframes(labels)
        save_tone_timeframes(chosen)
        self._tone_book.set_timeframes(chosen)
        self._tone_generation += 1
        self._tone_fill = "full"
        self._tone_epoch += 1
        self._tone_resync.set()
        return self.tone_timeframes_view()

    def _perp_indexes(self) -> list[int]:
        return sorted(meta.market_index for meta in self._markets.values() if meta.is_perp)

    async def on_tone_candles(
        self,
        market_index: int,
        resolution: str,
        bars: Sequence[Mapping[str, Any]],
    ) -> None:
        if not bars:
            return
        candles = [
            Candle(
                time=int(bar["time"]),
                open=float(bar["open"]),
                high=float(bar["high"]),
                low=float(bar["low"]),
                close=float(bar["close"]),
                volume=float(bar["volume"]),
            )
            for bar in bars
        ]
        alerts = getattr(self, "_alerts", None)
        if resolution == "1m" and alerts is not None:
            alerts.on_minute_bars(market_index, candles)
        book = getattr(self, "_tone_book", None)
        if book is not None and resolution in book.timeframes:
            await book.observe_off_loop(market_index, resolution, candles, now=time.time())

    def tone_channels(self) -> list[str]:
        labels = set(self._tone_book.timeframes)
        labels.add("1m")
        ordered = sorted(labels, key=lambda x: TONE_TIMEFRAME_SECONDS.get(x, 0))
        return [
            f"candle/{market_index}/{label}"
            for market_index in self._perp_indexes()
            for label in ordered
        ]

    async def _alert_minute_backfill_loop(self) -> None:
        await asyncio.sleep(2)
        while True:
            try:
                await self._backfill_alert_minute_books()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("alert minute backfill failed")
            await asyncio.sleep(3600)

    async def _funding_backfill_loop(self) -> None:
        """Once a day, fill a year of settled funding for perps not yet backfilled: hours, then days."""
        # Wait for live prints: the backfill checks the venue's rows against them.
        await asyncio.sleep(300)
        while True:
            try:
                perps = sorted(
                    (m for m in self._markets.values() if m.is_perp),
                    key=lambda m: to_float(m.volume_24h),
                    reverse=True,
                )
                await backfill_funding(perps, self._fetch_fundings, now=time.time())
                await backfill_funding_days(perps, self._fetch_fundings, now=time.time())
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("funding backfill failed")
            await asyncio.sleep(86_400)

    async def _fetch_fundings(
        self, market_index: int, end_ms: int, count: int, resolution: str
    ) -> list[dict[str, Any]]:
        await budget.take("background", wait=True)
        step_ms = 86_400_000 if resolution == "1d" else 3_600_000
        resp = await lighter.CandlestickApi(self.client).fundings(
            market_id=market_index,
            resolution=resolution,
            start_timestamp=max(0, end_ms - count * step_ms),
            end_timestamp=end_ms,
            count_back=count,
        )
        return [row.to_dict() for row in (getattr(resp, "fundings", None) or [])]

    async def _backfill_alert_minute_books(self) -> None:
        perps = sorted(
            (m for m in self._markets.values() if m.is_perp),
            key=lambda m: to_float(m.volume_24h),
            reverse=True,
        )
        book = self._alerts.minute_book()
        for meta in perps:
            if book.seeded(meta.market_index):
                continue
            try:
                candles = await self.get_candles(
                    meta.market_index, "1m", _ALERT_MINUTE_BARS, lane="background"
                )
            except Exception:
                logger.exception("alert minute seed failed market=%s", meta.market_index)
                continue
            self._alerts.seed_minute_bars(meta.market_index, candles)

    async def _breathe(self) -> None:
        """Let a due timer run before the next market.

        ponytail: the ceiling is one market, two z-scores. asyncio.sleep(0) is a
        call_soon, so the next market jumps ahead of a timer that is already due
        and the timer's wakeup waits behind that market too. A zero-delay timer
        waits behind the overdue one. Split the two scores if one market is ever
        over the lag budget.
        """
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        handle = loop.call_later(0, future.set_result, None)
        try:
            await future
        except asyncio.CancelledError:
            handle.cancel()
            future.cancel()
            raise

    async def _pace(self, rows: Iterator[dict[str, Any] | None]) -> list[dict[str, Any]]:
        """Run one market, then let the loop handle everything else."""
        built: list[dict[str, Any]] = []
        for row in rows:
            if row is not None:
                built.append(row)
            await self._breathe()
        return built

    async def paced_scan_activity(self) -> list[dict[str, Any]]:
        rows = await self._pace(self._alerts.iter_activity())
        rows.sort(key=lambda row: str(row["symbol"]))
        return rows

    async def paced_tone_board(self) -> list[dict[str, Any]]:
        rows = await self._pace(self._iter_tone())
        rows.sort(key=lambda row: (-int(row["closed_at"]), str(row["symbol"])))
        return rows

    async def paced_funding_extremes(self) -> list[dict[str, Any]]:
        rows = await self._pace(self._alerts.iter_funding_extremes())
        rows.sort(key=lambda row: (-abs(float(row["z"])), str(row["symbol"])))
        return rows

    async def _publish_scan_boards(self) -> None:
        for kind, rows in (
            ("scan_activity", await self.paced_scan_activity()),
            ("tone_board", await self.paced_tone_board()),
            ("funding_extremes", await self.paced_funding_extremes()),
        ):
            sig = json.dumps(rows, sort_keys=True, default=str)
            if sig == self._last_scan.get(kind):
                continue
            self._last_scan[kind] = sig
            self.broadcast({"type": kind, "rows": rows})

    async def _scan_loop(self) -> None:
        """Push each Scan board when it has changed. One market, then the loop."""
        while True:
            try:
                await asyncio.sleep(_SCAN_BROADCAST_S)
                await self._publish_scan_boards()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("scan board broadcast failed")

    def _request_tone_fill(self, kind: str) -> None:
        if self._tone_fill != "full":
            self._tone_fill = kind
        self._tone_resync.set()

    async def _tone_loop(self) -> None:
        while True:
            try:
                await self._tone_resync.wait()
                kind = self._tone_fill or "full"
                self._tone_fill = ""
                self._tone_resync.clear()
                generation = self._tone_generation
                if kind == "stale":
                    await self._backfill_tone_windows(generation, only_gaps=True)
                else:
                    await self._backfill_tone_windows(generation)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("tone alert cycle failed")
                await asyncio.sleep(5)

    async def _backfill_tone_windows(self, generation: int, *, only_gaps: bool = False) -> None:
        if only_gaps:
            wanted = self._tone_book.gaps(self._perp_indexes(), now=time.time())
        else:
            wanted = [
                (market_index, resolution)
                for market_index in self._perp_indexes()
                for resolution in self._tone_book.timeframes
            ]
        if not wanted:
            return
        logger.info("tone backfill %d windows", len(wanted))
        for market_index, resolution in wanted:
            if generation != self._tone_generation or self._tone_fill == "full":
                return
            try:
                candles = await self.get_candles(
                    market_index, resolution, _TONE_BACKFILL, lane="background"
                )
            except Exception:
                logger.exception("tone backfill failed market=%s %s", market_index, resolution)
                continue
            if generation != self._tone_generation:
                return
            await self._tone_book.seed_off_loop(market_index, resolution, candles, now=time.time())
