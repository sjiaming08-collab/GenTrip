"""HTTP response construction shared by synchronous and streamed plan results."""

from __future__ import annotations

from ..graph.state import token_usage_from_calls
from ..services.plan_service import degraded_reasons_from_state, infer_reply_type, next_suggested_moves
from .schemas import AgentReplyMetaResponse, PlanResponse


def response_from_state(state: dict) -> PlanResponse:
    reply_type = infer_reply_type(state)
    route_results = state.get("route_results", [])
    llm_calls = state.get("llm_calls") or []
    return PlanResponse(
        run_id=state["run_id"],
        turn_id=state.get("turn_id"),
        session_id=state.get("session_id"),
        run_status=state.get("run_status", "completed"),
        plan_path=state.get("plan_path"),
        assumptions=state.get("assumptions", []),
        route_results=route_results,
        structured=route_results,
        presentation=state.get("presentation"),
        current_phase=state.get("current_phase", "done"),
        reply_type=reply_type,
        planning_outcome=state.get("planning_outcome", "pending"),
        diff_result=state.get("diff_result"),
        meta=AgentReplyMetaResponse(
            plan_path=state.get("plan_path"),
            assumptions=state.get("assumptions", []),
            relaxed_constraints=state.get("relaxed_constraints", []),
            degraded=bool(state.get("degraded", False)),
            next_suggested_user_moves=next_suggested_moves(state, reply_type),
            phase_log=state.get("phase_log") or [],
            llm_calls=llm_calls,
            tool_calls=state.get("tool_calls") or [],
            data_sources=sorted({str(item.get("source")) for item in (state.get("tool_calls") or []) if item.get("source")}),
            degraded_reasons=degraded_reasons_from_state(state),
            token_usage=token_usage_from_calls(llm_calls),
            debug_trace_id=state.get("trace_id") or state.get("run_id"),
            planning_decision=state.get("planning_decision"),
            turn_plan=state.get("turn_plan"),
            turn_context_meta=state.get("turn_context_meta"),
            pending_change=state.get("pending_change"),
            rejected_change=state.get("rejected_change"),
            compiled_constraints=state.get("compiled_constraints"),
            active_policies=state.get("active_policies") or [],
            dropped_policies=state.get("dropped_policies") or [],
            blueprint_feasibility=state.get("blueprint_feasibility") or [],
            planning_failures=state.get("planning_failures") or [],
            repair_actions=state.get("repair_actions") or [],
        ),
    )
