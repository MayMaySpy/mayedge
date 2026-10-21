from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from mayedge.api.schemas import ToneTimeframesRequest
from mayedge.lighter.gateway import gateway

router = APIRouter()


@router.get("/api/scan/activity")
async def get_scan_activity() -> list[dict[str, Any]]:
    return await gateway.paced_scan_activity()


@router.get("/api/scan/tones")
async def get_scan_tones() -> list[dict[str, Any]]:
    return await gateway.paced_tone_board()


@router.get("/api/scan/tones/timeframes")
async def get_tone_timeframes() -> dict[str, Any]:
    return gateway.tone_timeframes_view()


@router.put("/api/scan/tones/timeframes")
async def put_tone_timeframes(body: ToneTimeframesRequest) -> dict[str, Any]:
    try:
        return gateway.set_tone_timeframes(body.timeframes)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
