"""Reliable SSE delivery for persisted plan run events."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from .container import plan_service
from .presentation import response_from_state

router = APIRouter()
_TERMINAL = {"completed", "failed", "cancelled", "degraded"}


def _encode(event: dict) -> str:
    payload = json.dumps(event, ensure_ascii=False, default=str)
    return f"id: {event['event_id']}\nevent: phase\ndata: {payload}\n\n"


def _complete_event(event_id: int, run: dict) -> str:
    payload: dict = {"phase": "complete", "status": run["status"], "run_id": run["run_id"]}
    if run.get("result") and run["status"] in {"completed", "degraded"}:
        payload["response"] = response_from_state(run["result"]).model_dump(mode="json")
    return f"id: {event_id}\nevent: complete\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


async def _event_stream(request: Request, run_id: str, after_event_id: int):
    last_event_id = after_event_id
    while True:
        for event in await plan_service.get_events_after(run_id, last_event_id):
            last_event_id = int(event["event_id"])
            yield _encode(event)
        run = await plan_service.get_run(run_id)
        if run is None:
            return
        if run["status"] in _TERMINAL:
            yield _complete_event(last_event_id, run)
            return
        if await request.is_disconnected():
            return
        await asyncio.sleep(0.25)


@router.get("/routes/plan/runs/{run_id}/events")
async def run_events(request: Request, run_id: str):
    run = await plan_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run_not_found")
    try:
        last_event_id = int(request.headers.get("last-event-id", "0"))
    except ValueError:
        last_event_id = 0
    return StreamingResponse(
        _event_stream(request, run_id, last_event_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/routes/plan/stream")
async def plan_stream(
    request: Request,
    query: str = Query(min_length=1),
    user_id: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
    session_id: str | None = None,
):
    """Compatibility endpoint: creates an async run and immediately streams it."""
    started = await plan_service.start_plan(
        query,
        user_id=user_id,
        user_lat=lat,
        user_lng=lng,
        session_id=session_id,
    )
    return StreamingResponse(
        _event_stream(request, started["run_id"], 0),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
