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
    run_status: str
    plan_path: Optional[str]
    current_phase: str
    error: Optional[str]
    degraded: bool

    # L1 INPUT
    user_query: str
    user_id: Optional[str]
    user_lat: Optional[float]
    user_lng: Optional[float]
    input_ts: str

    # L2 REASONING
    constraints: Optional[dict]
    assumptions: Annotated[list[dict], merge_assumptions]
    constraint_embedding: Optional[list[float]]
    relaxed_constraints: Annotated[list[str], operator.add]

    # L3 WORKING (HOT 字段预留，Step B 使用)
    bundle_candidates: list
    bundle_match_score: float
    matched_bundle_id: Optional[str]
    candidate_pois: list
    candidate_pois_by_dim: dict
    retrieval_meta: Optional[dict]
    candidate_routes: list
    valid_routes: list
    scored_routes: list
    validation_reports: list

    # L4 OUTPUT
    route_results: list
    presentation: Optional[dict]

    # L5 TELEMETRY
    phase_log: Annotated[list[dict], operator.add]
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
        run_status="running",
        plan_path=None,
        current_phase="init",
        error=None,
        degraded=False,
        user_query=user_query,
        user_id=user_id,
        user_lat=user_lat,
        user_lng=user_lng,
        input_ts=utc_now_iso(),
        constraints=None,
        assumptions=[],
        constraint_embedding=None,
        relaxed_constraints=[],
        bundle_candidates=[],
        bundle_match_score=0.0,
        matched_bundle_id=None,
        candidate_pois=[],
        candidate_pois_by_dim={},
        retrieval_meta=None,
        candidate_routes=[],
        valid_routes=[],
        scored_routes=[],
        validation_reports=[],
        route_results=[],
        presentation=None,
        phase_log=[],
        stream_events=[],
    )


def phase_update(phase: str, **extra: Any) -> dict:
    entry = {"phase": phase, "ts": utc_now_iso()}
    return {"current_phase": phase, "phase_log": [entry], **extra}
