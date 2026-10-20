from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from mayedge import desk
from mayedge.api.deps import _require_trading
from mayedge.api.schemas import AlgoStopRequest

router = APIRouter()


@router.get("/api/algos")
async def get_algos() -> dict[str, Any]:
    return desk.algo_book()


@router.post("/api/algos/stop")
async def stop_algos(req: AlgoStopRequest = AlgoStopRequest()) -> dict[str, Any]:
    return await desk.stop_algo(req.algo_id if req else None)


@router.post("/api/algos/pause")
async def pause_algos(req: AlgoStopRequest) -> dict[str, Any]:
    _require_trading()
    if not req.algo_id:
        raise HTTPException(400, "algo_id required")
    try:
        return await desk.pause_algo(req.algo_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/api/algos/unpause")
async def unpause_algos(req: AlgoStopRequest) -> dict[str, Any]:
    _require_trading()
    if not req.algo_id:
        raise HTTPException(400, "algo_id required")
    try:
        return await desk.unpause_algo(req.algo_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/api/algos/planner/preview")
async def preview_planner(body: dict[str, Any]) -> dict[str, Any]:
    try:
        return desk.planner_book.preview_from_body(body)
    except (ValueError, ArithmeticError, KeyError) as e:
        raise HTTPException(400, str(e)) from e


@router.post("/api/algos/planner/replan")
async def replan_planner(body: dict[str, Any]) -> dict[str, Any]:
    _require_trading()
    try:
        await desk.planner_book.replan_from_body(body)
    except (ValueError, ArithmeticError, KeyError) as e:
        raise HTTPException(400, str(e)) from e
    return desk.algo_book()


@router.post("/api/algos/planner/finish-entry")
async def finish_planner_entry(body: dict[str, Any]) -> dict[str, Any]:
    _require_trading()
    try:
        await desk.planner_book.finish_entry(str(body.get("algo_id") or ""))
    except (ValueError, ArithmeticError, KeyError) as e:
        raise HTTPException(400, str(e)) from e
    return desk.algo_book()


@router.post("/api/algos/trail/preview")
async def preview_trail(body: dict[str, Any]) -> dict[str, Any]:
    try:
        return desk.trail_book.preview_from_body(body)
    except (ValueError, ArithmeticError, KeyError) as e:
        raise HTTPException(400, str(e)) from e


@router.post("/api/algos/trail/edit")
async def edit_trail(body: dict[str, Any]) -> dict[str, Any]:
    _require_trading()
    try:
        await desk.trail_book.edit_from_body(body)
    except (ValueError, ArithmeticError, KeyError) as e:
        raise HTTPException(400, str(e)) from e
    return desk.algo_book()


@router.post("/api/algos/trail/stop")
async def stop_trail(body: dict[str, Any]) -> dict[str, Any]:
    algo_id = str(body.get("algo_id") or "")
    if not desk.trail_book.has(algo_id):
        raise HTTPException(404, f"Unknown Trail {algo_id!r}")
    await desk.trail_book.stop(algo_id, keep_stop=bool(body.get("keep_stop")))
    return desk.algo_book()


@router.get("/api/algos/{algo_type}")
async def get_algo_type(algo_type: str) -> dict[str, Any]:
    book = desk.get_book(algo_type)
    if book is None:
        raise HTTPException(404, f"Unknown algo type {algo_type!r}")
    return book.to_dict()


@router.post("/api/algos/{algo_type}/start")
async def start_algo(algo_type: str, body: dict[str, Any]) -> dict[str, Any]:
    book = desk.get_book(algo_type)
    if book is None:
        raise HTTPException(404, f"Unknown algo type {algo_type!r}")
    _require_trading()
    try:
        await book.start_from_body(body)
    except (ValueError, ArithmeticError, KeyError) as e:
        raise HTTPException(400, str(e)) from e
    return desk.algo_book()
