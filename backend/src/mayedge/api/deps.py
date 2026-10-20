"""Shared request helpers for the desk API."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from mayedge.lighter.budget import budget
from mayedge.lighter.errors import VenueBlocked, venue_client_error
from mayedge.lighter.gateway import gateway

logger = logging.getLogger(__name__)


def _market_index(symbol: str) -> int:
    try:
        return gateway.resolve_market_index(symbol)
    except ValueError as e:
        raise HTTPException(404, "Market not found") from e


def _order_service() -> Any:
    # Tests replace the name on the app module. Read it from there.
    from mayedge.api import app as api_app

    return api_app.order_service


def _require_trading() -> None:
    if not _order_service().enabled:
        raise HTTPException(503, "Trading not configured. Set API credentials in .env")


async def _trade(fn):
    _require_trading()
    try:
        result = await fn()
    except VenueBlocked as e:
        raise HTTPException(e.status, str(e)) from e
    except ValueError as e:
        logger.info("order rejected: %s", e)
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        mapped = venue_client_error(e)
        if mapped:
            raise HTTPException(mapped[0], mapped[1]) from e
        logger.exception("trade failed")
        raise HTTPException(502, "Venue error — try again") from e
    return result


async def _account_history(fn):
    token = budget.enter_lane("read")
    try:
        return await fn()
    except VenueBlocked as e:
        raise HTTPException(e.status, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        mapped = venue_client_error(e)
        if mapped:
            raise HTTPException(mapped[0], mapped[1]) from e
        logger.exception("account history failed")
        raise HTTPException(502, "Venue error — try again") from e
    finally:
        budget.leave_lane(token)
