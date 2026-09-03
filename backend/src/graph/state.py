"""GraphState — LangGraph 节点间共享状态。"""

from __future__ import annotations

import logging
import operator
from datetime import datetime, timezone
from typing import Annotated, Any, Optional, TypedDict
from uuid import uuid4

logger = logging.getLogger("gentrip.graph")


def merge_assumptions(existing: list[dict], new: list[dict]) -> list[dict]:
    by_slot = {item["slot"]: item for item in existing}
    for item in new:
        by_slot[item["slot"]] = item
    return list(by_slot.values())


class GraphState(TypedDict, total=False):
    # L0 RUN_META
    run_id: str
    session_id: Optional[str]
    tenant_id: str
    turn_id: str
    run_mode: str
    turn_mode: str
    turn_relation: str
    recompute_scope: str
    run_status: str
    plan_path: Optional[str]
    planning_outcome: str
    planning_decision: Optional[dict]
    current_phase: str
    error: Optional[str]
    degraded: bool
    relax_attempt: int

    # L1 INPUT
    user_query: str
    user_id: Optional[str]
    user_lat: Optional[float]
    user_lng: Optional[float]
    input_ts: str

    # L2 REASONING
    constraints: Optional[dict]
    compiled_constraints: Optional[dict]
    active_policies: list
    dropped_policies: list
    constraint_provenance: Optional[dict]
    original_constraints: Optional[dict]
    geo_scope: Optional[dict]
    route_intent: Optional[dict]
    turn_plan: Optional[dict]
    constraint_patch: Optional[dict]
    turn_context_meta: Optional[dict]
    memory_context: Optional[dict]
    assumptions: Annotated[list[dict], merge_assumptions]
    constraint_embedding: Optional[list[float]]
    relaxed_constraints: Annotated[list[str], operator.add]

    # L3 WORKING (HOT 字段预留，Step B 使用)
    session_current_route: Optional[dict]
    bundle_candidates: list
    bundle_match_score: float
    matched_bundle_id: Optional[str]
    activity_blueprints: list
    blueprint_feasibility: list
    planning_failures: list
    repair_actions: list
    repair_applied: bool
    selected_blueprint_id: Optional[str]
    candidate_pois: list
    candidate_pois_by_slot: dict
    candidate_pois_by_dim: dict
    retrieval_meta: Optional[dict]
    route_generation_meta: Optional[dict]
    route_evaluation_meta: Optional[dict]
    candidate_routes: list
    valid_routes: list
    scored_routes: list
    validation_reports: list

    # L3 WORKING — Replan 子图
    replan_operation: Optional[dict]
    replan_operations: list[dict]
    original_route: Optional[dict]
    locked_stop_indices: list[int]
    unlocked_slots: list
    replacement_candidates: list
    delta_valid: bool
    delta_retry_count: int
    diff_result: Optional[dict]
    replan_proposals: list[dict]
    pending_change: Optional[dict]
    rejected_change: Optional[dict]
    explicitly_locked_stop_indices: list[int]

    # L4 OUTPUT
    route_results: list
    presentation: Optional[dict]
    reply_type: Optional[str]
    agent_reply_meta: Optional[dict]

    # L5 TELEMETRY
    phase_log: Annotated[list[dict], operator.add]
    llm_calls: Annotated[list[dict], operator.add]
    tool_calls: Annotated[list[dict], operator.add]
    stream_events: Annotated[list[dict], operator.add]
    runtime_run_id: Optional[str]
    trace_id: Optional[str]
    resume_next_node: Optional[str]
    resumed_from_phase: Optional[str]
    resume_count: int


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_initial_state(
    user_query: str,
    *,
    user_id: str | None = None,
    user_lat: float | None = None,
    user_lng: float | None = None,
    session_id: str | None = None,
    tenant_id: str = "default",
) -> GraphState:
    """创建 Plan Run 初始状态，所有键必须有默认值。"""
    return GraphState(
        run_id=str(uuid4()),
        session_id=session_id,
        tenant_id=tenant_id,
        turn_id=str(uuid4()),
        run_mode="plan",
        turn_mode="plan",
        turn_relation="new_goal",
        recompute_scope="global_rebuild",
        run_status="running",
        plan_path=None,
        planning_outcome="pending",
        planning_decision=None,
        current_phase="init",
        error=None,
        degraded=False,
        relax_attempt=0,
        user_query=user_query,
        user_id=user_id,
        user_lat=user_lat,
        user_lng=user_lng,
        input_ts=utc_now_iso(),
        constraints=None,
        compiled_constraints=None,
        active_policies=[],
        dropped_policies=[],
        constraint_provenance=None,
        original_constraints=None,
        geo_scope=None,
        route_intent=None,
        turn_plan=None,
        constraint_patch=None,
        turn_context_meta=None,
        memory_context=None,
        assumptions=[],
        constraint_embedding=None,
        relaxed_constraints=[],
        session_current_route=None,
        bundle_candidates=[],
        bundle_match_score=0.0,
        matched_bundle_id=None,
        activity_blueprints=[],
        blueprint_feasibility=[],
        planning_failures=[],
        repair_actions=[],
        repair_applied=False,
        selected_blueprint_id=None,
        candidate_pois=[],
        candidate_pois_by_slot={},
        candidate_pois_by_dim={},
        retrieval_meta=None,
        route_generation_meta=None,
        route_evaluation_meta=None,
        candidate_routes=[],
        valid_routes=[],
        scored_routes=[],
        replan_operation=None,
        replan_operations=[],
        original_route=None,
        locked_stop_indices=[],
        unlocked_slots=[],
        replacement_candidates=[],
        delta_valid=True,
        delta_retry_count=0,
        diff_result=None,
        replan_proposals=[],
        pending_change=None,
        rejected_change=None,
        explicitly_locked_stop_indices=[],
        validation_reports=[],
        route_results=[],
        presentation=None,
        reply_type=None,
        agent_reply_meta=None,
        phase_log=[],
        llm_calls=[],
        tool_calls=[],
        stream_events=[],
        runtime_run_id=None,
        trace_id=None,
        resume_next_node=None,
        resumed_from_phase=None,
        resume_count=0,
    )


def phase_update(phase: str, status: str = "completed", summary: str | None = None, **extra: Any) -> dict:
    entry = {"phase": phase, "status": status, "ts": utc_now_iso()}
    if summary:
        entry["summary"] = summary
    logger.info("[%s] %s%s", phase, status, f" — {summary}" if summary else "")
    return {"current_phase": phase, "phase_log": [entry], **extra}


def log_step(phase: str, **kv: Any) -> None:
    """Log structured key=value pairs for a graph step."""
    parts = " ".join(f"{k}={v}" for k, v in kv.items())
    logger.info("[%s] %s", phase, parts)


def normalize_llm_call(
    *,
    operation: str,
    status: str,
    provider: str = "deepseek",
    model: str | None = None,
    latency_ms: float = 0,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    fallback_used: bool = False,
    source: str | None = None,
    attempt_count: int = 1,
    error_code: str | None = None,
    circuit_state: str | None = None,
    max_tokens: int | None = None,
    thinking_enabled: bool | None = None,
    skip_reason: str | None = None,
) -> dict:
    return {
        "operation": operation,
        "provider": provider,
        "model": model,
        "status": status,
        "prompt_tokens": int(prompt_tokens or 0),
        "completion_tokens": int(completion_tokens or 0),
        "total_tokens": int(total_tokens or 0),
        "latency_ms": latency_ms,
        "fallback_used": fallback_used,
        "source": source or operation,
        "attempt_count": int(attempt_count or 0),
        "error_code": error_code,
        "circuit_state": circuit_state,
        "max_tokens": max_tokens,
        "thinking_enabled": thinking_enabled,
        "skip_reason": skip_reason,
    }


def llm_call_from_meta(
    operation: str,
    meta: dict[str, Any] | None,
    *,
    status: str | None = None,
    fallback_used: bool = False,
    source: str | None = None,
) -> dict:
    meta = meta or {}
    return normalize_llm_call(
        operation=operation,
        provider=str(meta.get("provider") or "deepseek"),
        model=meta.get("model"),
        status=status or str(meta.get("status") or "success"),
        latency_ms=meta.get("latency_ms") or 0,
        prompt_tokens=meta.get("prompt_tokens") or 0,
        completion_tokens=meta.get("completion_tokens") or 0,
        total_tokens=meta.get("total_tokens") or 0,
        fallback_used=fallback_used,
        source=source,
        attempt_count=meta.get("attempt_count") if meta.get("attempt_count") is not None else 1,
        error_code=meta.get("error_code"),
        circuit_state=meta.get("circuit_state"),
        max_tokens=meta.get("max_tokens"),
        thinking_enabled=meta.get("thinking_enabled"),
        skip_reason=meta.get("skip_reason"),
    )


def token_usage_from_calls(calls: list[dict]) -> dict:
    counted = [call for call in calls if call.get("status") != "skipped"]
    return {
        "prompt_tokens": sum(int(call.get("prompt_tokens") or 0) for call in counted),
        "completion_tokens": sum(int(call.get("completion_tokens") or 0) for call in counted),
        "total_tokens": sum(int(call.get("total_tokens") or 0) for call in counted),
        "call_count": len(counted),
    }
