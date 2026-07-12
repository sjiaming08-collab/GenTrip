"""HTTP response construction shared by synchronous and streamed plan results."""

from __future__ import annotations

from ..graph.state import token_usage_from_calls
from ..services.plan_service import infer_reply_type
from .schemas import AgentReplyMetaResponse, PlanResponse


def suggestions_for(reply_type: str) -> list[str]:
    if reply_type == "reject":
        return ["附近有什么好玩的", "徐汇逛吃", "黄浦区看展览再喝咖啡"]
    return ["换个预算", "增加一家咖啡", "换到静安区"]


def response_from_state(state: dict) -> PlanResponse:
    reply_type = infer_reply_type(state)
    route_results = state.get("route_results", [])
    llm_calls = state.get("llm_calls") or []
    return PlanResponse(
        run_id=state["run_id"],
        session_id=state.get("session_id"),
        run_status=state.get("run_status", "completed"),
        plan_path=state.get("plan_path"),
        assumptions=state.get("assumptions", []),
        route_results=route_results,
        structured=route_results,
        presentation=state.get("presentation"),
        current_phase=state.get("current_phase", "done"),
        reply_type=reply_type,
        meta=AgentReplyMetaResponse(
            plan_path=state.get("plan_path"),
            assumptions=state.get("assumptions", []),
            relaxed_constraints=state.get("relaxed_constraints", []),
            degraded=bool(state.get("degraded", False)),
            next_suggested_user_moves=suggestions_for(reply_type),
            phase_log=state.get("phase_log") or [],
            llm_calls=llm_calls,
            token_usage=token_usage_from_calls(llm_calls),
            debug_trace_id=state.get("run_id"),
        ),
    )
