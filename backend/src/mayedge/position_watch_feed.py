"""What the Position watch reads (docs/position-rules.md PW1), from what the desk already holds.

One 1h candle read per closed hour per Position whose Idea has a stop (E4). Nothing else leaves
the desk, and nothing here places, amends or cancels an order.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from mayedge import desk
from mayedge.lighter.account import account_service
from mayedge.lighter.gateway import gateway
from mayedge.lighter.models import to_float
from mayedge.lighter.orders import protect_role_kind
from mayedge.persist_ideas import ideas_list
from mayedge.position_watch import (
    CLOSE_S,
    GUARD_ALGOS,
    GUARD_STATUS,
    Held,
    IdeaStop,
    Look,
    StopOrder,
    idea_stop,
)

logger = logging.getLogger(__name__)

# Market index → (hour it was read for, close of the last closed 1h bar).
_closes: dict[int, tuple[int, float]] = {}


def _open_trips() -> dict[tuple[int, str], dict[str, Any]]:
    from mayedge.api.routes.journal import last_open

    rows = (last_open() or {}).get("positions") or []
    out: dict[tuple[int, str], dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict):
            out[(int(row.get("market_index") or 0), str(row.get("side") or ""))] = row
    return out


def _positions() -> list[Held]:
    trips = _open_trips()
    out: list[Held] = []
    for pos in account_service.cached_summary().positions:
        size = to_float(pos.size)
        if size == 0:
            continue
        meta = gateway.get_market_by_index(pos.market_index)
        live = meta.mark_price if meta and meta.mark_price else None
        trip = trips.get((pos.market_index, pos.side))
        out.append(
            Held(
                market_index=pos.market_index,
                symbol=pos.symbol,
                side=pos.side,
                size=abs(size),
                entry=to_float(pos.entry_price),
                mark=live or to_float(pos.mark_price),
                liq=to_float(pos.liquidation_price),
                trip=str(trip.get("trip_key") or "") if trip else "",
                funding=to_float(trip.get("funding")) if trip else None,
            )
        )
    return out


def _stops() -> list[StopOrder]:
    out: list[StopOrder] = []
    for order in account_service.list_open_orders():
        role = protect_role_kind(order.order_type)
        if role is None or role[0] != "sl":
            continue
        out.append(StopOrder(order.market_index, order.side, to_float(order.trigger_price)))
    return out


def _guarded() -> set[int]:
    rows = desk.algo_book().get("working") or []
    return {
        int(row.get("market_index") or 0)
        for row in rows
        if row.get("algo_type") in GUARD_ALGOS and row.get("status") in GUARD_STATUS
    }


def _ideas() -> list[IdeaStop]:
    out: list[IdeaStop] = []
    for row in ideas_list("open"):
        stop = to_float(row.get("stop"))
        if stop <= 0:
            continue
        out.append(
            IdeaStop(
                symbol=str(row.get("symbol") or ""),
                side=str(row.get("side") or ""),
                stop=stop,
                updated_at=int(row.get("updated_at") or 0),
            )
        )
    return out


def _crowded() -> dict[int, tuple[float, float]]:
    return {
        int(row["market_index"]): (float(row["funding"]), float(row["z"]))
        for row in gateway.funding_extremes()
    }


async def _close(market_index: int, now: float) -> float | None:
    """E4. The last closed 1h bar, read once per hour."""
    hour = int(now) // CLOSE_S
    cached = _closes.get(market_index)
    if cached is not None and cached[0] == hour:
        return cached[1]
    try:
        bars = await gateway.get_candles(market_index, "1h", 3, lane="background")
    except Exception:
        logger.exception("position watch 1h read failed market=%s", market_index)
        return cached[1] if cached else None
    closed = [bar for bar in bars if bar.time + CLOSE_S <= now and bar.close > 0]
    if not closed:
        return None
    close = closed[-1].close
    _closes[market_index] = (hour, close)
    return close


async def gather() -> Look:
    positions = _positions()
    ideas = await asyncio.to_thread(_ideas)
    now = time.time()
    closes: dict[int, float] = {}
    for pos in positions:
        if idea_stop(pos, ideas) is None:
            continue
        close = await _close(pos.market_index, now)
        if close is not None:
            closes[pos.market_index] = close
    held = {pos.market_index for pos in positions}
    for mi in list(_closes):
        if mi not in held:
            del _closes[mi]
    return Look(
        positions=positions,
        stops=_stops(),
        guarded=_guarded(),
        ideas=ideas,
        crowded=_crowded(),
        closes=closes,
    )
