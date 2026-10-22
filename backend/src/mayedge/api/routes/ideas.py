"""Idea routes. SQLite only; Last comes from the market the desk already holds. Rules: docs/idea-rules.md."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

from mayedge import persist_idea_alerts as alerts_store
from mayedge.api import responses
from mayedge.api.responses import documents
from mayedge.api.schemas import (
    IdeaAlertBody,
    IdeaBody,
    IdeaLogBody,
    IdeaPatch,
    IdeaPlannerBody,
    IdeaReviewBody,
    IdeaStatusBody,
)
from mayedge.idea_alert_watch import gateway_quote
from mayedge.idea_alerts import spec_of
from mayedge.ideas import Refusal, last_text, normalise
from mayedge.lighter.gateway import gateway
from mayedge.persist_ideas import (
    Missing,
    NotAllowed,
    Stale,
    idea_delete,
    idea_get,
    idea_insert,
    idea_log_add,
    idea_planner,
    idea_review,
    idea_status,
    idea_update,
    ideas_list,
)

router = APIRouter()


def _refused(err: Refusal) -> HTTPException:
    return HTTPException(422, {"field": err.field, "message": err.message})


def _last(symbol: str) -> str | None:
    meta = gateway.get_market(symbol)
    if meta is None:
        return None
    return last_text(meta.last_trade_price, meta.mark_price, meta.mid_price)


async def _call(fn: Any, *args: Any) -> Any:
    try:
        return await asyncio.to_thread(fn, *args)
    except Missing:
        raise HTTPException(404, "No such Idea.") from None
    except Stale:
        raise HTTPException(409, {"message": "Changed elsewhere, reloaded"}) from None
    except NotAllowed:
        raise HTTPException(409, {"message": "That status move is not allowed."}) from None
    except Refusal as err:
        raise _refused(err) from None


@router.get("/api/ideas", response_model=None, responses=documents(responses.Ideas))
async def get_ideas(status: str | None = None) -> dict[str, Any]:
    try:
        ideas = await asyncio.to_thread(ideas_list, status)
    except ValueError:
        raise HTTPException(
            400, "status must be watching, active, closed, dropped, open, or all"
        ) from None
    return {"ideas": ideas}


@router.get("/api/ideas/{idea_id}", response_model=None, responses=documents(responses.IdeaDetail))
async def get_idea(idea_id: str) -> dict[str, Any]:
    found = await asyncio.to_thread(idea_get, idea_id)
    if found is None:
        raise HTTPException(404, "No such Idea.")
    return found


@router.post("/api/ideas", response_model=None, responses=documents(responses.IdeaCreated))
async def post_idea(body: IdeaBody) -> dict[str, Any]:
    got = normalise(body.model_dump())
    if isinstance(got, Refusal):
        raise _refused(got)
    idea, warning = await _call(idea_insert, got, _last(got.symbol))
    return {"idea": idea, "warning": warning}


@router.patch("/api/ideas/{idea_id}", response_model=None, responses=documents(responses.IdeaSaved))
async def patch_idea(idea_id: str, body: IdeaPatch) -> dict[str, Any]:
    fields = body.model_dump(exclude_unset=True)
    seen = int(fields.pop("seen_updated_at"))
    symbol = fields.get("symbol")
    last_symbol = symbol if isinstance(symbol, str) and symbol.strip() else None
    if last_symbol is None:
        current = await asyncio.to_thread(idea_get, idea_id)
        if current is None:
            raise HTTPException(404, "No such Idea.")
        last_symbol = str(current["idea"]["symbol"])
    idea = await _call(idea_update, idea_id, fields, seen, _last(last_symbol))
    return {"idea": idea}


@router.post(
    "/api/ideas/{idea_id}/status",
    response_model=None,
    responses=documents(responses.IdeaSaved),
)
async def post_status(idea_id: str, body: IdeaStatusBody) -> dict[str, Any]:
    current = await asyncio.to_thread(idea_get, idea_id)
    if current is None:
        raise HTTPException(404, "No such Idea.")
    idea = await _call(
        idea_status,
        idea_id,
        body.status,
        body.outcome,
        body.review,
        _last(str(current["idea"]["symbol"])),
    )
    return {"idea": idea}


@router.patch(
    "/api/ideas/{idea_id}/review",
    response_model=None,
    responses=documents(responses.IdeaSaved),
)
async def patch_review(idea_id: str, body: IdeaReviewBody) -> dict[str, Any]:
    idea = await _call(idea_review, idea_id, body.model_dump(exclude_unset=True))
    return {"idea": idea}


@router.post(
    "/api/ideas/{idea_id}/log",
    response_model=None,
    responses=documents(responses.IdeaLogged),
)
async def post_log(idea_id: str, body: IdeaLogBody) -> dict[str, Any]:
    current = await asyncio.to_thread(idea_get, idea_id)
    if current is None:
        raise HTTPException(404, "No such Idea.")
    line = await _call(idea_log_add, idea_id, body.body, _last(str(current["idea"]["symbol"])))
    return {"line": line}


@router.post(
    "/api/ideas/{idea_id}/planner",
    response_model=None,
    responses=documents(responses.IdeaSaved),
)
async def post_planner(idea_id: str, body: IdeaPlannerBody) -> dict[str, Any]:
    current = await asyncio.to_thread(idea_get, idea_id)
    if current is None:
        raise HTTPException(404, "No such Idea.")
    idea = await _call(idea_planner, idea_id, body.algo_id, _last(str(current["idea"]["symbol"])))
    return {"idea": idea}


@router.delete("/api/ideas/{idea_id}", status_code=204)
async def delete_idea(idea_id: str) -> None:
    await _call(idea_delete, idea_id)


async def _alert_call(fn: Any, *args: Any) -> Any:
    try:
        return await asyncio.to_thread(fn, *args)
    except alerts_store.Missing:
        raise HTTPException(404, "No such Idea or alert.") from None
    except Refusal as err:
        raise _refused(err) from None


async def _symbol_of(idea_id: str) -> str:
    current = await asyncio.to_thread(idea_get, idea_id)
    if current is None:
        raise HTTPException(404, "No such Idea.")
    return str(current["idea"]["symbol"])


@router.get(
    "/api/ideas/{idea_id}/alerts",
    response_model=None,
    responses=documents(responses.IdeaAlerts),
)
async def get_alerts(idea_id: str) -> dict[str, Any]:
    await _symbol_of(idea_id)
    return {"alerts": await asyncio.to_thread(alerts_store.alerts_for, idea_id)}


@router.post(
    "/api/ideas/{idea_id}/alerts",
    response_model=None,
    responses=documents(responses.IdeaAlertSaved),
)
async def post_alert(idea_id: str, body: IdeaAlertBody) -> dict[str, Any]:
    spec = spec_of(body.model_dump())
    if isinstance(spec, Refusal):
        raise _refused(spec)
    last, change = gateway_quote(await _symbol_of(idea_id))
    alert = await _alert_call(alerts_store.alert_add, idea_id, spec, last, change)
    return {"alert": alert}


@router.post(
    "/api/ideas/{idea_id}/alerts/plan",
    response_model=None,
    responses=documents(responses.IdeaAlerts),
)
async def post_plan_alerts(idea_id: str) -> dict[str, Any]:
    last, _ = gateway_quote(await _symbol_of(idea_id))
    if last is None:
        raise HTTPException(422, {"field": "kind", "message": "No Last for this Market yet."})
    made = await _alert_call(alerts_store.alerts_from_plan, idea_id, last)
    return {"alerts": made}


@router.post(
    "/api/idea-alerts/{alert_id}/rearm",
    response_model=None,
    responses=documents(responses.IdeaAlertSaved),
)
async def post_rearm(alert_id: int) -> dict[str, Any]:
    found = await asyncio.to_thread(alerts_store.alert_symbol, alert_id)
    if found is None:
        raise HTTPException(404, "No such alert.")
    last, change = gateway_quote(found)
    alert = await _alert_call(alerts_store.alert_rearm, alert_id, last, change)
    return {"alert": alert}


@router.delete("/api/idea-alerts/{alert_id}", status_code=204)
async def delete_alert(alert_id: int) -> None:
    await _alert_call(alerts_store.alert_delete, alert_id)
