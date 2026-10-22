"""Journal routes. Round trips are rebuilt on read. Rules: docs/journal-rules.md."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal
from typing import Any, cast

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from mayedge.api import responses
from mayedge.api.responses import documents
from mayedge.api.turn import breathe
from mayedge.config import settings
from mayedge.journal import GroupBy, RoundTrip, seconds_of, summary
from mayedge.journal import round_trips as build_trips
from mayedge.journal_build import JournalInputs, load_inputs
from mayedge.journal_build import build as build_off_loop
from mayedge.journal_excursion import excursion, resolution_for
from mayedge.journal_sync import run_sync
from mayedge.lighter.account import account_service
from mayedge.lighter.gateway import gateway
from mayedge.numbers import fmt_decimal
from mayedge.persist_journal import (
    journal_generation,
    journal_load_excursion,
    journal_load_notes,
    journal_put_excursion,
    journal_put_note,
)
from mayedge.tone_compute import call

router = APIRouter()

_RANGES = {"7d": 7, "30d": 30, "90d": 90, "all": None}
_GROUPS = {"day", "market", "algo", "none"}
_cache_lock = threading.Lock()
_cache: tuple[int, JournalInputs] | None = None
_ready: tuple[tuple[str, int], list[RoundTrip]] | None = None
_build_lock: asyncio.Lock | None = None
_lock_loop: asyncio.AbstractEventLoop | None = None


class NoteBody(BaseModel):
    note: str = ""
    tags: list[str] = Field(default_factory=list)


@router.get("/api/journal/trips", response_model=None, responses=documents(responses.JournalTrips))
async def get_trips(
    since: int | None = None,
    until: int | None = None,
    market: str | None = None,
    algo: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    upnl = _upnl()
    trips = [
        trip
        for trip in await _shared_trips(upnl)
        if _market_ok(trip, market) and _algo_ok(trip, algo) and _span_ok(trip, since, until)
    ]
    trips.sort(key=lambda trip: trip.close_ts or trip.open_ts, reverse=True)
    capped = trips[: max(1, min(limit, 500))]
    notes = journal_load_notes()
    return {"trips": [_trip_json(trip, notes) for trip in capped]}


@router.get(
    "/api/journal/summary", response_model=None, responses=documents(responses.JournalSummary)
)
async def get_summary(
    range: str = "30d",
    group: str = "none",
    market: str | None = None,
    algo: str | None = None,
) -> dict[str, Any]:
    if range not in _RANGES:
        raise HTTPException(400, "range must be 7d, 30d, 90d, or all")
    if group not in _GROUPS:
        raise HTTPException(400, "group must be day, market, algo, or none")
    days = _RANGES[range]
    since = None if days is None else int(time.time()) - days * 86_400
    upnl = _upnl()
    chosen = [
        trip
        for trip in await _shared_trips(upnl)
        if _closed_since(trip, since) and _market_ok(trip, market) and _algo_ok(trip, algo)
    ]
    rows = summary(chosen, cast(GroupBy, group))
    return {
        "range": range,
        "group": group,
        "groups": [_summary_json(row) for row in rows],
    }


@router.put(
    "/api/journal/trips/{trip_key}/note",
    response_model=None,
    responses=documents(responses.JournalNote),
)
async def put_note(trip_key: str, body: NoteBody) -> dict[str, Any]:
    await asyncio.to_thread(journal_put_note, trip_key, body.note, body.tags)
    return {"trip_key": trip_key, "note": body.note, "tags": body.tags}


@router.post("/api/journal/sync", response_model=None, responses=documents(responses.JournalSync))
async def post_sync() -> dict[str, Any]:
    return await run_sync()


def _inputs() -> JournalInputs:
    """Parsed fills and the rest, reused until a journal write bumps the generation."""
    global _cache
    gen = journal_generation()
    with _cache_lock:
        if _cache is not None and _cache[0] == gen:
            return _cache[1]
        data = load_inputs()
        if journal_generation() == gen:
            _cache = (gen, data)
        return data


def _build_lock_for() -> asyncio.Lock:
    global _build_lock, _lock_loop
    loop = asyncio.get_running_loop()
    if _build_lock is None or _lock_loop is not loop:
        _build_lock = asyncio.Lock()
        _lock_loop = loop
    return _build_lock


def _stamp(trips: list[RoundTrip], upnl: dict[int, Decimal]) -> list[RoundTrip]:
    """Live uPnL changes every tick. It is not part of the rebuild."""
    if not any(trip.open for trip in trips):
        return trips
    return [
        replace(trip, upnl=upnl.get(trip.market_index)) if trip.open else trip for trip in trips
    ]


_open_emit: Callable[[dict[str, Any]], None] | None = None
_last_open: dict[str, Any] | None = None


def set_open_emitter(fn: Callable[[dict[str, Any]], None] | None) -> None:
    global _open_emit
    _open_emit = fn


def last_open() -> dict[str, Any] | None:
    """The last `journal_open` sent, for a tab that connects later."""
    return _last_open


def open_payload(trips: list[RoundTrip]) -> dict[str, Any]:
    """Each open Round trip's Realized: venue PnL on its closes less its fees (journal-rules, On a Position)."""
    return {
        "type": "journal_open",
        "positions": [
            {
                "market_index": trip.market_index,
                "symbol": trip.symbol,
                "side": trip.side,
                "trip_key": trip.trip_key,
                "open_ts": trip.open_ts,
                "realized": _num(trip.pnl - trip.fees),
                "pnl": _num(trip.pnl),
                "fees": _num(trip.fees),
                "funding": _num(trip.funding),
                "net": _num(trip.net),
                "partial": trip.partial,
            }
            for trip in trips
            if trip.open
        ],
    }


async def warm() -> None:
    """One rebuild before the first page, so that open reads the cache. Sends `journal_open`."""
    global _last_open
    payload = open_payload(await _shared_trips(_upnl()))
    _last_open = payload
    if _open_emit is not None:
        _open_emit(payload)


@router.get(
    "/api/journal/trips/{trip_key}/excursion",
    response_model=None,
    responses=documents(responses.JournalExcursion),
)
async def get_excursion(trip_key: str) -> dict[str, Any]:
    """A Round trip's Excursion (journal-rules, Excursion). Read once for a closed trip, then kept."""
    trip = next((t for t in await _shared_trips(_upnl()) if t.trip_key == trip_key), None)
    if trip is None:
        raise HTTPException(404, "No such Round trip")
    out: dict[str, Any] = {
        "trip_key": trip_key,
        "open": trip.open,
        "resolution": None,
        "mae_pct": None,
        "mfe_pct": None,
        "mae_usd": None,
        "mfe_usd": None,
    }
    if trip.avg_in is None:
        return out
    sig = f"{trip.close_ts}:{trip.avg_in}:{trip.size}"
    if not trip.open:
        kept = await asyncio.to_thread(journal_load_excursion, trip_key, sig)
        if kept is not None:
            return {**out, **kept}
    open_s = seconds_of(trip.open_ts)
    close_s = seconds_of(trip.close_ts) if trip.close_ts else int(time.time())
    name, step, count = resolution_for(open_s, close_s)
    candles = await gateway.get_candles(
        trip.market_index, name, count, end_ms=(close_s + step) * 1000
    )
    found = excursion(trip.side, trip.avg_in, trip.size, candles, open_s, close_s, name, step)
    if found is None:
        return out
    read = {
        "resolution": found.resolution,
        "mae_pct": _num(found.mae_pct),
        "mfe_pct": _num(found.mfe_pct),
        "mae_usd": _num(found.mae_usd),
        "mfe_usd": _num(found.mfe_usd),
    }
    if not trip.open:
        await asyncio.to_thread(journal_put_excursion, trip_key, sig, read)
    return {**out, **read}


@router.get("/api/journal/open", response_model=None, responses=documents(responses.JournalOpen))
async def get_open() -> dict[str, Any]:
    return open_payload(await _shared_trips(_upnl()))


async def _shared_trips(upnl: dict[int, Decimal]) -> list[RoundTrip]:
    """One rebuild per database generation. Readers of that rebuild take turns."""
    global _ready
    sig = (settings.db_path, journal_generation())
    if _ready is not None and _ready[0] == sig:
        return _stamp(_ready[1], upnl)
    async with _build_lock_for():
        if _ready is None or _ready[0] != sig:
            built = await call(build_off_loop, settings.db_path, {})
            _ready = (sig, built)
        trips = _ready[1]
    await breathe()
    return _stamp(trips, upnl)


def _trips(upnl: dict[int, Decimal] | None = None) -> list[RoundTrip]:
    fills, funding, links, risk, oldest = _inputs()
    return build_trips(
        fills,
        funding,
        links,
        risk,
        oldest_ts=oldest,
        upnl=_upnl() if upnl is None else upnl,
    )


def _upnl() -> dict[int, Decimal]:
    out: dict[int, Decimal] = {}
    for pos in account_service._summary.positions:
        try:
            out[pos.market_index] = Decimal(str(pos.unrealized_pnl or "0"))
        except (ArithmeticError, ValueError):
            continue
    return out


def _market_ok(trip: RoundTrip, market: str | None) -> bool:
    if not market:
        return True
    if market.isdigit():
        return trip.market_index == int(market)
    return trip.symbol.upper() == market.upper()


def _algo_ok(trip: RoundTrip, algo: str | None) -> bool:
    """Empty is every Round trip. `algos` is every algo family, manual left out."""
    if not algo:
        return True
    if algo == "algos":
        return trip.algo != "manual"
    return trip.algo == algo


def _span_ok(trip: RoundTrip, since: int | None, until: int | None) -> bool:
    stamp = seconds_of(trip.close_ts or trip.open_ts)
    if since is not None and stamp < seconds_of(since):
        return False
    if until is not None and stamp > seconds_of(until):
        return False
    return True


def _closed_since(trip: RoundTrip, since: int | None) -> bool:
    if trip.open or trip.partial or trip.close_ts is None:
        return False
    return since is None or seconds_of(trip.close_ts) >= since


def _num(value: Decimal | None) -> str | None:
    return None if value is None else fmt_decimal(value)


def _trip_json(trip: RoundTrip, notes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    note = notes.get(trip.trip_key) or {}
    return {
        "trip_key": trip.trip_key,
        "market_index": trip.market_index,
        "symbol": trip.symbol,
        "side": trip.side,
        "open_ts": trip.open_ts,
        "close_ts": trip.close_ts,
        "size": _num(trip.size),
        "avg_in": _num(trip.avg_in),
        "avg_out": _num(trip.avg_out),
        "pnl": _num(trip.pnl),
        "fees": _num(trip.fees),
        "funding": _num(trip.funding),
        "net": _num(trip.net),
        "algo": trip.algo,
        "algo_id": trip.algo_id,
        "r": _num(trip.r),
        "partial": trip.partial,
        "partial_reason": trip.partial_reason,
        "open": trip.open,
        "upnl": _num(trip.upnl),
        "note": str(note.get("note") or ""),
        "tags": note.get("tags") or [],
        "fills": [
            {
                "trade_id": part.trade_id,
                "ts": part.ts,
                "side": part.side,
                "price": _num(part.price),
                "size": _num(part.size),
                "fee": _num(part.fee),
                "pnl": _num(part.pnl),
                "is_maker": part.is_maker,
                "closing": part.closing,
            }
            for part in trip.fills
        ],
    }


def _summary_json(row: Any) -> dict[str, Any]:
    return {
        "key": row.key,
        "count": row.count,
        "wins": row.wins,
        "losses": row.losses,
        "win_rate": _num(row.win_rate),
        "gross_pnl": _num(row.gross_pnl),
        "fees": _num(row.fees),
        "funding": _num(row.funding),
        "net": _num(row.net),
        "avg_win": _num(row.avg_win),
        "avg_loss": _num(row.avg_loss),
        "profit_factor": _num(row.profit_factor),
        "expectancy": _num(row.expectancy),
        "largest_win": _num(row.largest_win),
        "largest_loss": _num(row.largest_loss),
        "maker_share": _num(row.maker_share),
        "avg_r": _num(row.avg_r),
        "total_r": _num(row.total_r),
        "r_count": row.r_count,
        "max_drawdown": _num(row.max_drawdown),
        "payoff_ratio": _num(row.payoff_ratio),
        "breakeven_win_rate": _num(row.breakeven_win_rate),
        "notional": _num(row.notional),
        "net_bps": _num(row.net_bps),
        "recovery_factor": _num(row.recovery_factor),
        "max_win_streak": row.max_win_streak,
        "max_loss_streak": row.max_loss_streak,
        "current_streak": row.current_streak,
        "avg_hold_win_s": _num(row.avg_hold_win_s),
        "avg_hold_loss_s": _num(row.avg_hold_loss_s),
        "long": _side_json(row.long),
        "short": _side_json(row.short),
        "trading_days": row.trading_days,
        "green_days": row.green_days,
        "best_day": _num(row.best_day),
        "worst_day": _num(row.worst_day),
        "curve": [{"ts": point.ts, "net": _num(point.net)} for point in row.curve],
    }


def _side_json(side: Any) -> dict[str, Any] | None:
    if side is None:
        return None
    return {"count": side.count, "win_rate": _num(side.win_rate), "net": _num(side.net)}
