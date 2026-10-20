from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from mayedge.lighter.gateway import gateway
from mayedge.push import TelegramPusher, public_push_status

router = APIRouter()


@router.get("/api/alerts")
async def get_alerts(limit: int = 200) -> list[dict[str, Any]]:
    cap = max(1, min(int(limit), 1000))
    return gateway.recent_alerts()[:cap]


@router.get("/api/alerts/stats")
async def get_alert_stats(hours: int = 24) -> dict[str, Any]:
    span = max(1, min(int(hours), 24 * 30))
    return gateway.alert_stats(span)


@router.get("/api/alerts/funding")
async def get_funding_extremes() -> list[dict[str, Any]]:
    return gateway.funding_extremes()


@router.post("/api/alerts/{alert_id}/opened")
async def post_alert_opened(alert_id: str) -> dict[str, str]:
    if not gateway.alert_opened(alert_id):
        raise HTTPException(404, "Alert not found")
    return {"status": "ok"}


@router.get("/api/push")
async def get_push() -> dict[str, Any]:
    return public_push_status()


@router.post("/api/push/test")
async def post_push_test(request: Request) -> dict[str, Any]:
    pusher: TelegramPusher | None = getattr(request.app.state, "pusher", None)
    if pusher is None:
        return {"ok": False, "error": "Pushes are off"}
    return await pusher.test_push()
