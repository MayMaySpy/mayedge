"""Rebuild Round trips off the desk loop.

Parsing the fills and replaying them holds the GIL for longer than the lag
budget. The worker does not share the GIL. It loads the rows itself so the
desk does not pickle them, and it does not import the gateway: that import
is most of a cold rebuild and it lands on the first Journal open.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from mayedge.journal import Fill, FundingPayment, RoundTrip


def imports_gateway(db_path: str, upnl: dict[int, Decimal]) -> bool:
    """Test probe. A spawned worker imports this module, not the test module."""
    import sys

    build(db_path, upnl)
    return "mayedge.lighter.gateway" in sys.modules


def build(db_path: str, upnl: dict[int, Decimal]) -> list[RoundTrip]:
    from mayedge import db as store
    from mayedge.config import settings

    if settings.db_path != db_path:
        settings.db_path = db_path
        store.close_db()
    from mayedge.journal import round_trips as build_trips
    from mayedge.persist_journal import (
        journal_load_fills,
        journal_load_funding,
        journal_load_links,
        journal_load_planner_risk,
        journal_oldest_ts,
    )

    risk = {
        algo_id: (Decimal(entry), Decimal(stop))
        for algo_id, (entry, stop) in journal_load_planner_risk().items()
    }
    return build_trips(
        [_fill(row) for row in journal_load_fills()],
        [_funding(row) for row in journal_load_funding()],
        journal_load_links(),
        risk,
        oldest_ts=journal_oldest_ts(),
        upnl=upnl,
    )


def _fill(row: dict[str, Any]) -> Fill:
    return Fill(
        trade_id=str(row["trade_id"]),
        market_index=int(row["market_index"]),
        symbol=str(row["symbol"]),
        side=str(row["side"]),
        is_maker=bool(row["is_maker"]),
        price=Decimal(str(row["price"])),
        size=Decimal(str(row["size"])),
        usd=Decimal(str(row["usd"])),
        fee=Decimal(str(row["fee"])),
        pnl=Decimal(str(row["pnl"])),
        kind=str(row["kind"]),
        ts=int(row["ts"]),
    )


def _funding(row: dict[str, Any]) -> FundingPayment:
    return FundingPayment(
        market_index=int(row["market_index"]),
        ts=int(row["ts"]),
        amount=Decimal(str(row["amount"])),
    )
