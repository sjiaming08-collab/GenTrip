"""Reliable SSE delivery for persisted plan run events."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from .container import plan_service
from .presentation import response_from_state
from .tenant_auth import RequestIdentity, resolve_identity
from ..runtime.task_queue import QueueUnavailable
from ..services.auth_service import AuthService

router = APIRouter()
_TERMINAL = {"completed", "failed", "cancelled", "degraded", "timed_out"}


async def _request_identity(request: Request, requested_tenant: str | None = None) -> RequestIdentity:
    identity = resolve_identity(request, requested_tenant)
    if identity.user_id:
        await AuthService(plan_service._store).load_identity(identity.user_id, identity.tenant_id)
    return identity


async def _ensure_run_owner(run: dict, identity: RequestIdentity) -> None:
    if not identity.user_id:
        return
    requested_user = (run.get("request") or {}).get("user_id")
    if requested_user and requested_user != identity.user_id:
        raise HTTPException(status_code=404, detail="run_not_found")
    session = await plan_service.load_session(run["session_id"], tenant_id=identity.tenant_id)
    if session and session.user_id and session.user_id != identity.user_id:
        raise HTTPException(status_code=404, detail="run_not_found")


def _encode(event: dict) -> str:
    payload = json.dumps(event, ensure_ascii=False, default=str)
    return f"id: {event['event_id']}\nevent: phase\ndata: {payload}\n\n"


def _complete_event(event_id: int, run: dict) -> str:
    payload: dict = {"phase": "complete", "status": run["status"], "run_id": run["run_id"]}
    if run.get("result") and run["status"] in {"completed", "degraded"}:
        payload["response"] = response_from_state(run["result"]).model_dump(mode="json")
    return f"id: {event_id}\nevent: complete\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


async def _event_stream(request: Request, run_id: str, after_event_id: int, tenant_id: str):
    last_event_id = after_event_id
    while True:
        for event in await plan_service.get_events_after(run_id, last_event_id, tenant_id=tenant_id):
            last_event_id = int(event["event_id"])
            yield _encode(event)
        run = await plan_service.get_run(run_id, tenant_id=tenant_id)
        if run is None:
            return
        if run["status"] in _TERMINAL:
            yield _complete_event(last_event_id, run)
            return
        if await request.is_disconnected():
            return
        await asyncio.sleep(0.25)


@router.get("/routes/plan/runs/{run_id}/events")
async def run_events(request: Request, run_id: str, tenant_id: str = "default"):
    identity = await _request_identity(request, tenant_id)
    run = await plan_service.get_run(run_id, tenant_id=identity.tenant_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run_not_found")
    await _ensure_run_owner(run, identity)
    try:
        last_event_id = int(request.headers.get("last-event-id", "0"))
    except ValueError:
        last_event_id = 0
    return StreamingResponse(
        _event_stream(request, run_id, last_event_id, identity.tenant_id),
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
    tenant_id: str = "default",
):
    """Compatibility endpoint: creates an async run and immediately streams it."""
    identity = await _request_identity(request, tenant_id)
    try:
        started = await plan_service.start_plan(
            query,
            tenant_id=identity.tenant_id,
            user_id=identity.user_id or user_id,
            user_lat=lat,
            user_lng=lng,
            session_id=session_id,
        )
    except QueueUnavailable as exc:
        raise HTTPException(status_code=503, detail="plan_queue_unavailable") from exc
    return StreamingResponse(
        _event_stream(request, started["run_id"], 0, identity.tenant_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
