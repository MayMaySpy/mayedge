from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from mayedge import desk
from mayedge.api.deps import _require_trading
from mayedge.api.schemas import AutoKillRequest, KillRequest
from mayedge.lighter.account import account_service

router = APIRouter()


def _auto_kill():
    # Tests replace the name on the app module. Read it from there.
    from mayedge.api import app as api_app

    return api_app.auto_kill


@router.post("/api/kill")
async def kill_switch(req: KillRequest) -> dict[str, Any]:
    from mayedge.api.app import run_kill

    result = await run_kill(flatten=req.flatten)
    return {**result.as_dict(), "algos": desk.algo_book()}


@router.get("/api/kill/auto")
async def get_auto_kill() -> dict[str, Any]:
    return _auto_kill().view()


@router.put("/api/kill/auto")
async def put_auto_kill(body: AutoKillRequest) -> dict[str, Any]:
    if body.armed:
        _require_trading()
    cached = account_service.cached_account_payload()
    positions = (cached or {}).get("positions") or []
    try:
        return _auto_kill().configure(
            armed=body.armed,
            loss_usd=body.loss_usd,
            profit_usd=body.profit_usd,
            current_positions=positions if body.armed else None,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
