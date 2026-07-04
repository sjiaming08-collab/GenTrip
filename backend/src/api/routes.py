"""HTTP 路由。"""

from fastapi import APIRouter, HTTPException

from ..config import settings
from ..graph.state import token_usage_from_calls
from ..services.plan_service import PlanService, infer_reply_type
from .schemas import AgentReplyMetaResponse, PlanRequest, PlanResponse, SessionResponse

router = APIRouter()
_plan_service = PlanService()


def _suggestions_for(reply_type: str) -> list[str]:
    if reply_type == "reject":
        return ["附近有什么好玩的", "徐汇逛吃", "黄浦区看展览再喝咖啡"]
    return ["换个预算", "增加一家咖啡", "换到静安区"]


def _response_from_state(state: dict) -> PlanResponse:
    reply_type = infer_reply_type(state)
    route_results = state.get("route_results", [])
    llm_calls = state.get("llm_calls") or []
    meta = AgentReplyMetaResponse(
        plan_path=state.get("plan_path"),
        assumptions=state.get("assumptions", []),
        relaxed_constraints=state.get("relaxed_constraints", []),
        degraded=bool(state.get("degraded", False)),
        next_suggested_user_moves=_suggestions_for(reply_type),
        phase_log=state.get("phase_log") or [],
        llm_calls=llm_calls,
        token_usage=token_usage_from_calls(llm_calls),
        debug_trace_id=state.get("run_id"),
    )
    return PlanResponse(
        run_id=state["run_id"],
        session_id=state.get("session_id"),
        run_status=state["run_status"],
        plan_path=state.get("plan_path"),
        assumptions=state.get("assumptions", []),
        route_results=route_results,
        structured=route_results,
        presentation=state.get("presentation"),
        current_phase=state.get("current_phase", "done"),
        reply_type=reply_type,
        meta=meta,
    )


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "app": settings.app_name,
        "step": "A-cold-path",
        "runtime_stage": "P2-turn-orchestrator",
    }


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    session = _plan_service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    return SessionResponse(
        session_id=session.session_id,
        turn_count=session.turn_count,
        mode=session.mode,
        current_route=session.current_route,
        dialog_summary=session.dialog_summary,
        assumptions=session.assumptions,
        route_intent=session.route_intent.model_dump(mode="json") if session.route_intent else None,
        recent_turns=[turn.model_dump(mode="json") for turn in session.recent_turns],
    )


@router.post("/routes/plan", response_model=PlanResponse)
async def plan_route(request: PlanRequest):
    state = await _plan_service.run_plan(
        request.query,
        user_id=request.user_id,
        user_lat=request.lat,
        user_lng=request.lng,
        session_id=request.session_id,
    )
    if state.get("run_status") != "completed":
        raise HTTPException(
            status_code=500,
            detail=state.get("error") or "plan_run_failed",
        )
    return _response_from_state(state)
