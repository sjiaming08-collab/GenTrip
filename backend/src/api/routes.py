"""HTTP routes for synchronous and asynchronous route planning."""

from fastapi import APIRouter, HTTPException

from ..config import settings
from .container import plan_service
from .presentation import response_from_state
from .schemas import (
    FeedbackRequest,
    PlanRequest,
    PlanResponse,
    PlanRunStartedResponse,
    RunStatusResponse,
    SessionListResponse,
    SessionResponse,
    SessionUpdateRequest,
)

router = APIRouter()


@router.get("/health")
async def health():
    dependencies = await plan_service.health()
    required_dependencies = [dependencies["database"]]
    if settings.redis_url:
        required_dependencies.append(dependencies["redis"])
    return {
        "status": "ok" if all(required_dependencies) else "degraded",
        "app": settings.app_name,
        "step": "A-cold-path",
        "runtime_stage": "P2-turn-orchestrator",
        "runtime_mode": "persistent" if plan_service.persistent else "in_memory_test",
        "dependencies": dependencies,
    }


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    session = await plan_service.load_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    turns = await plan_service.load_turns(session_id)
    return SessionResponse(
        session_id=session.session_id,
        title=session.title,
        turn_count=session.turn_count,
        mode=session.mode,
        current_route=session.current_route,
        dialog_summary=session.dialog_summary,
        assumptions=session.assumptions,
        route_intent=session.route_intent.model_dump(mode="json") if session.route_intent else None,
        recent_turns=[turn.model_dump(mode="json") for turn in session.recent_turns],
        turns=[turn.model_dump(mode="json") for turn in turns],
        latest_response=session.latest_response,
    )


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(user_id: str | None = None, limit: int = 30):
    rows = await plan_service.list_sessions(user_id, limit=min(max(limit, 1), 100))
    return SessionListResponse(sessions=rows)


@router.patch("/sessions/{session_id}", response_model=SessionResponse)
async def update_session(session_id: str, request: SessionUpdateRequest):
    session = await plan_service.rename_session(session_id, request.title)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    turns = await plan_service.load_turns(session_id)
    return SessionResponse(
        session_id=session.session_id,
        title=session.title,
        turn_count=session.turn_count,
        mode=session.mode,
        current_route=session.current_route,
        dialog_summary=session.dialog_summary,
        assumptions=session.assumptions,
        route_intent=session.route_intent.model_dump(mode="json") if session.route_intent else None,
        recent_turns=[turn.model_dump(mode="json") for turn in session.recent_turns],
        turns=[turn.model_dump(mode="json") for turn in turns],
        latest_response=session.latest_response,
    )


@router.post("/routes/plan", response_model=PlanResponse)
async def plan_route(request: PlanRequest):
    state = await plan_service.run_plan(
        request.query,
        user_id=request.user_id,
        user_lat=request.lat,
        user_lng=request.lng,
        session_id=request.session_id,
    )
    if state.get("run_status") == "failed":
        raise HTTPException(status_code=500, detail=state.get("error") or "plan_run_failed")
    if state.get("run_status") == "cancelled":
        raise HTTPException(status_code=409, detail="plan_run_cancelled")
    return response_from_state(state)


@router.post("/routes/plan/runs", response_model=PlanRunStartedResponse, status_code=202)
async def start_plan_run(request: PlanRequest):
    started = await plan_service.start_plan(
        request.query,
        user_id=request.user_id,
        user_lat=request.lat,
        user_lng=request.lng,
        session_id=request.session_id,
    )
    return PlanRunStartedResponse(**started)


@router.get("/routes/plan/runs/{run_id}", response_model=RunStatusResponse)
async def get_plan_run(run_id: str):
    run = await plan_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run_not_found")
    result = run.get("result")
    return RunStatusResponse(
        run_id=run["run_id"],
        session_id=run["session_id"],
        status=run["status"],
        error_code=run.get("error_code"),
        result=response_from_state(result) if result and result.get("run_status") != "failed" else None,
    )


@router.post("/routes/plan/runs/{run_id}/cancel")
async def cancel_plan_run(run_id: str):
    if not await plan_service.cancel_run(run_id):
        raise HTTPException(status_code=409, detail="run_not_cancellable")
    return {"run_id": run_id, "status": "cancelled"}


@router.post("/routes/feedback")
async def submit_feedback(request: FeedbackRequest):
    session = await plan_service.load_session(request.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")

    if request.action == "confirm":
        session.mode = "completed"
        if request.poi_id and request.poi_id not in session.confirmed_stop_ids:
            session.confirmed_stop_ids.append(request.poi_id)
    elif request.action == "reject_poi" and request.poi_id:
        if request.poi_id not in session.rejected_poi_ids:
            session.rejected_poi_ids.append(request.poi_id)
    elif request.action == "rate" and request.route_id:
        session.route_feedback.append(
            {
                "route_id": request.route_id,
                "score": request.score,
                "comment": request.comment,
            }
        )
        session.route_feedback = session.route_feedback[-50:]
    elif request.action == "overturn_assumption" and request.overturned_assumption:
        session.mode = "replanning"
        if request.overturned_assumption not in session.overridden_slots:
            session.overridden_slots.append(request.overturned_assumption)
    await plan_service.save_session(session)
    return {"status": "ok", "session_id": request.session_id, "mode": session.mode}
