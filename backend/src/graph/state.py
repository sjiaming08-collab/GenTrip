"""GraphState — LangGraph 节点间共享状态。"""

from __future__ import annotations

import operator
from datetime import datetime, timezone
from typing import Annotated, Any, Optional, TypedDict
from uuid import uuid4


def merge_assumptions(existing: list[dict], new: list[dict]) -> list[dict]:
    by_slot = {item["slot"]: item for item in existing}
    for item in new:
        by_slot[item["slot"]] = item
    return list(by_slot.values())


class GraphState(TypedDict, total=False):
    # L0 RUN_META
    run_id: str
    session_id: Optional[str]
    turn_id: str
    run_mode: str
    turn_mode: str
    run_status: str
    plan_path: Optional[str]
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
    geo_scope: Optional[dict]
    route_intent: Optional[dict]
    memory_context: Optional[dict]
    assumptions: Annotated[list[dict], merge_assumptions]
    constraint_embedding: Optional[list[float]]
    relaxed_constraints: Annotated[list[str], operator.add]

    # L3 WORKING (HOT 字段预留，Step B 使用)
    session_current_route: Optional[dict]
    bundle_candidates: list
    bundle_match_score: float
    matched_bundle_id: Optional[str]
    candidate_pois: list
    candidate_pois_by_dim: dict
    retrieval_meta: Optional[dict]
    route_generation_meta: Optional[dict]
    route_evaluation_meta: Optional[dict]
    candidate_routes: list
    valid_routes: list
    scored_routes: list
    validation_reports: list

    # L4 OUTPUT
    route_results: list
    presentation: Optional[dict]
    reply_type: Optional[str]
    agent_reply_meta: Optional[dict]

    # L5 TELEMETRY
    phase_log: Annotated[list[dict], operator.add]
    llm_calls: Annotated[list[dict], operator.add]
    stream_events: Annotated[list[dict], operator.add]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_initial_state(
    user_query: str,
    *,
    user_id: str | None = None,
    user_lat: float | None = None,
    user_lng: float | None = None,
    session_id: str | None = None,
) -> GraphState:
    """创建 Plan Run 初始状态，所有键必须有默认值。"""
    return GraphState(
        run_id=str(uuid4()),
        session_id=session_id,
        turn_id=str(uuid4()),
        run_mode="plan",
        turn_mode="plan",
        run_status="running",
        plan_path=None,
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
        geo_scope=None,
        route_intent=None,
        memory_context=None,
        assumptions=[],
        constraint_embedding=None,
        relaxed_constraints=[],
        session_current_route=None,
        bundle_candidates=[],
        bundle_match_score=0.0,
        matched_bundle_id=None,
        candidate_pois=[],
        candidate_pois_by_dim={},
        retrieval_meta=None,
        route_generation_meta=None,
        route_evaluation_meta=None,
        candidate_routes=[],
        valid_routes=[],
        scored_routes=[],
        validation_reports=[],
        route_results=[],
        presentation=None,
        reply_type=None,
        agent_reply_meta=None,
        phase_log=[],
        llm_calls=[],
        stream_events=[],
    )


def phase_update(phase: str, status: str = "completed", summary: str | None = None, **extra: Any) -> dict:
    entry = {"phase": phase, "status": status, "ts": utc_now_iso()}
    if summary:
        entry["summary"] = summary
    return {"current_phase": phase, "phase_log": [entry], **extra}


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
    )


def token_usage_from_calls(calls: list[dict]) -> dict:
    counted = [call for call in calls if call.get("status") != "skipped"]
    return {
        "prompt_tokens": sum(int(call.get("prompt_tokens") or 0) for call in counted),
        "completion_tokens": sum(int(call.get("completion_tokens") or 0) for call in counted),
        "total_tokens": sum(int(call.get("total_tokens") or 0) for call in counted),
        "call_count": len(counted),
    }
