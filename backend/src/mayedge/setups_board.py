"""The Setups board: rebuilt once an hour from what the desk already stores (setup-rules G1–G3).

No venue call and no order. Reads markets and daily bars the desk holds, and open interest,
funding prints and liquidations from the desk database.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import yaml

from mayedge.alert_settings import AlertSettings, resolve_alerts_config_path
from mayedge.lighter.gateway import gateway
from mayedge.lighter.models import MarketMeta
from mayedge.persist_funding import recent_funding_prints
from mayedge.persist_liq import summarize_liquidations
from mayedge.persist_oi import list_open_interest
from mayedge.persist_setups import record_setups, setups_listed_since
from mayedge.setups import (
    FUNDING_BASE_DAYS,
    MarketRead,
    Setup,
    SetupSettings,
    find_setups,
    setup_settings_from_dict,
)

logger = logging.getLogger(__name__)

_HOUR_S = 3_600
# G2. The first build waits for the daily bars; later ones run a minute past the hour.
FIRST_BUILD_S = 300.0
AFTER_HOUR_S = 60.0


def next_build_at(now: float) -> float:
    """G2. A minute past the next UTC hour."""
    return float((int(now) // _HOUR_S + 1) * _HOUR_S + AFTER_HOUR_S)


def load_setup_settings() -> SetupSettings:
    path = resolve_alerts_config_path()
    try:
        data = yaml.safe_load(path.read_text()) if path.is_file() else {}
    except Exception:
        logger.warning("setup settings unreadable at %s; using defaults", path)
        data = {}
    return setup_settings_from_dict(data if isinstance(data, dict) else {})


def liquid(meta: MarketMeta, thr: AlertSettings) -> bool:
    """G1, as alert-rules G2 reads it: 24h volume, then the spread when there is a quote."""
    if not meta.is_perp or meta.volume_24h < thr.min_24h_usd:
        return False
    bid, ask = meta.best_bid_price, meta.best_ask_price
    mid = meta.mid_price or meta.last_trade_price
    if not bid or not ask or not mid or mid <= 0:
        return True
    return (ask - bid) / mid * 10_000 <= thr.max_spread_bps


def _oi_at(series: list[dict[str, Any]], at_s: int) -> float | None:
    """The close of the hourly bucket that ended nearest ``at_s``, within an hour of it."""
    best: tuple[int, float] | None = None
    for row in series:
        end = int(row["time"]) + _HOUR_S
        gap = abs(end - at_s)
        if gap <= _HOUR_S and (best is None or gap < best[0]):
            best = (gap, float(row["open_interest"]))
    return best[1] if best else None


def _stored(
    indexes: list[int], now: float, cfg: SetupSettings
) -> tuple[dict[int, list[dict[str, Any]]], dict[int, dict[int, float]], dict[int, dict[str, Any]]]:
    """The database part: open interest by hour, funding prints, the last 4h of liquidations."""
    base_from = int(now) // _HOUR_S - cfg.funding_hours - FUNDING_BASE_DAYS * 24
    series = {mi: list_open_interest(mi, resolution="1h", count=30) for mi in indexes}
    since_ms = int(now * 1000) - 4 * _HOUR_S * 1000
    liqs = {int(r["market_index"]): r for r in summarize_liquidations(since_ms=since_ms)}
    return series, recent_funding_prints(base_from), liqs


async def read_markets(now: float, cfg: SetupSettings) -> tuple[list[MarketRead], float | None]:
    """Everything the board reads. The desk's own maps are read here, on the loop."""
    thr = gateway.alert_thresholds()
    metas = [m for m in gateway.list_markets() if liquid(m, thr)]
    strip = {int(r["market_index"]): float(r["z"]) for r in gateway.funding_extremes()}
    daily = {m.market_index: gateway.daily_bars(m.market_index) for m in metas}
    btc = gateway.get_market("BTC")
    oi, prints, liqs = await asyncio.to_thread(_stored, [m.market_index for m in metas], now, cfg)
    this_hour = int(now) // _HOUR_S
    window_from = this_hour - cfg.funding_hours
    base_from = window_from - FUNDING_BASE_DAYS * 24
    reads: list[MarketRead] = []
    for meta in metas:
        mi = meta.market_index
        series = oi.get(mi, [])
        by_hour = prints.get(mi, {})
        window = [by_hour[h] for h in range(window_from, this_hour) if h in by_hour]
        before = [by_hour[h] for h in range(base_from, window_from) if h in by_hour]
        liq = liqs.get(mi) or {}
        reads.append(
            MarketRead(
                market_index=mi,
                symbol=meta.symbol,
                last=meta.last_trade_price or meta.mark_price or 0.0,
                change_24h=meta.change_24h,
                oi_now=meta.open_interest or None,
                oi_24h_ago=_oi_at(series, int(now) - 24 * _HOUR_S),
                oi_4h_ago=_oi_at(series, int(now) - 4 * _HOUR_S),
                funding_z=strip.get(mi),
                funding_window=window,
                funding_before=before,
                funding_window_complete=len(window) == cfg.funding_hours,
                daily=daily.get(mi, []),
                liq_long_usd=float(liq.get("long_usd") or 0.0),
                liq_short_usd=float(liq.get("short_usd") or 0.0),
            )
        )
    return reads, (btc.change_24h if btc else None)


def row_view(s: Setup) -> dict[str, Any]:
    return {
        "kind": s.kind,
        "market_index": s.market_index,
        "symbol": s.symbol,
        "direction": s.direction,
        "size": round(s.size, 2),
        "price": s.price,
        "note": s.note,
    }


class SetupBoard:
    def __init__(
        self,
        cfg: SetupSettings | None = None,
        read: Callable[
            [float, SetupSettings], Awaitable[tuple[list[MarketRead], float | None]]
        ] = read_markets,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._cfg = cfg or load_setup_settings()
        self._read = read
        self._clock = clock
        self._rows: list[Setup] = []
        self._built_at: int | None = None
        self._listed: dict[tuple[int, str], int] | None = None
        self._task: asyncio.Task[None] | None = None

    def view(self) -> dict[str, Any]:
        return {"built_at": self._built_at, "rows": [row_view(s) for s in self._rows]}

    async def rebuild(self) -> list[Setup]:
        now = self._clock()
        now_ms = int(now * 1000)
        if self._listed is None:
            # R2 across a restart: a row listed at the last rebuild continues.
            self._listed = await asyncio.to_thread(setups_listed_since, now_ms - 2 * _HOUR_S * 1000)
        reads, btc = await self._read(now, self._cfg)
        board = find_setups(reads, btc, now, self._cfg)
        self._listed = await asyncio.to_thread(record_setups, board, self._listed, now_ms=now_ms)
        self._rows = board
        self._built_at = now_ms
        return board

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        await asyncio.sleep(FIRST_BUILD_S)
        while True:
            try:
                await self.rebuild()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("setups board rebuild failed")
            now = self._clock()
            await asyncio.sleep(max(1.0, next_build_at(now) - now))


_started: SetupBoard | None = None


def start() -> SetupBoard:
    global _started
    _started = SetupBoard()
    _started.start()
    return _started


async def stop() -> None:
    global _started
    if _started is not None:
        await _started.stop()
        _started = None


def current_view() -> dict[str, Any]:
    if _started is None:
        return {"built_at": None, "rows": []}
    return _started.view()
