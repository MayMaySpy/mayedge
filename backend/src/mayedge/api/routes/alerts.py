from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from mayedge.alert_log import UnknownKnob
from mayedge.lighter.gateway import gateway
from mayedge.push import TelegramPusher, public_push_status

router = APIRouter()


@router.get("/api/alerts")
async def get_alerts(limit: int = 200) -> list[dict[str, Any]]:
    cap = max(1, min(int(limit), 1000))
    return gateway.recent_alerts()[:cap]


@router.get("/api/alerts/stats")
async def get_alert_stats(hours: int = 24, by: str = "rule") -> dict[str, Any]:
    span = max(1, min(int(hours), 24 * 90))
    try:
        return gateway.alert_stats(span, by)
    except ValueError as exc:
        raise HTTPException(
            400, "by must be rule, rule_severity, rule_direction, held, hour, or symbol"
        ) from exc


@router.get("/api/alerts/settings")
async def get_alert_settings() -> dict[str, Any]:
    return gateway.alert_settings()


@router.get("/api/alerts/whatif")
async def get_alert_whatif(
    rule: str, knob: str, value: float, days: int = 30
) -> dict[str, Any]:
    span = days if days in (7, 30, 90) else None
    if span is None:
        raise HTTPException(400, "days must be 7, 30, or 90")
    try:
        return gateway.alert_whatif(rule=rule, knob=knob, value=value, days=span)
    except UnknownKnob as exc:
        raise HTTPException(400, f"unknown knob {knob}") from exc


@router.get("/api/alerts/funding")
async def get_funding_extremes() -> list[dict[str, Any]]:
    return await gateway.paced_funding_extremes()


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
