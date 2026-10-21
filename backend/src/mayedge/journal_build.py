"""Rebuild Round trips off the desk loop.

Parsing the fills and replaying them holds the GIL for longer than the lag
budget. The worker does not share the GIL. The database path is an argument
so a test's temporary file is the one that gets read.
"""

from __future__ import annotations

from decimal import Decimal

from mayedge.journal import RoundTrip


def build(db_path: str, upnl: dict[int, Decimal]) -> list[RoundTrip]:
    from mayedge import db as store
    from mayedge.config import settings

    if settings.db_path != db_path:
        settings.db_path = db_path
        store.close_db()
    from mayedge.api.routes import journal as routes

    routes._cache = None
    return routes._trips(upnl)
