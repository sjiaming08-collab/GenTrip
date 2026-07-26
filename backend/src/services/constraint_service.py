"""约束提取编排 — DeepSeek LLM + 规则降级。"""

from __future__ import annotations

import re

from pydantic import ValidationError

from ..config import settings
from ..graph.state import GraphState
from ..llm.constraint_extract_llm import llm_extract_constraint, llm_extract_constraint_with_meta
from ..llm.exceptions import LLMError
from ..llm.schemas import ConstraintExtractResult
from ..models.constraints import Assumption, Constraints, IntentDomain
from .constraint_rules import (
    DEFAULT_BUDGET,
    DEFAULT_DISTRICT,
    DEFAULT_MINUTES,
    DEFAULT_POI_COUNT,
    DISTRICTS,
    detect_excluded_categories,
    detect_preferred_cuisines,
    detect_minutes,
    detect_queue_tolerance_minutes,
    detect_domains,
    detect_start_at,
    detect_return_by,
    derive_time_budget_minutes,
    rule_based_extract,
)

_RETURN_BY_PATTERN = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")


def _valid_return_by(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if _RETURN_BY_PATTERN.match(value):
        return value
    return None


def _merge_assumptions(*groups: list[Assumption]) -> list[Assumption]:
    by_slot: dict[str, Assumption] = {}
    for group in groups:
        for item in group:
            by_slot[item.slot] = item
    return list(by_slot.values())


def _assumption(slot: str, value: str, message: str, *, source: str) -> Assumption:
    return Assumption(
        slot=slot,
        assumed_value=value,
        source=source,
        message=message,
    )


def _memory_value(state: GraphState, slot: str) -> str | None:
    memory = state.get("memory_context") or {}
    current_constraints = memory.get("current_constraints") or {}
    if current_constraints.get(slot) is not None:
        value = current_constraints.get(slot)
        if isinstance(value, list):
            return ",".join(str(item) for item in value)
        return str(value)
    for item in memory.get("assumptions") or []:
        if item.get("slot") == slot and item.get("assumed_value"):
            return str(item["assumed_value"])
    for turn in reversed(memory.get("recent_turns") or []):
        for item in turn.get("assumptions") or []:
            if item.get("slot") == slot and item.get("assumed_value"):
                return str(item["assumed_value"])
    return None

def _memory_int(state: GraphState, slot: str) -> int | None:
    raw = _memory_value(state, slot)
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def normalize_llm_result(
    result: ConstraintExtractResult,
    query: str,
    state: GraphState | None = None,
) -> tuple[Constraints, list[Assumption]]:
    state = state or GraphState(user_query=query)
    assumptions: list[Assumption] = [
        Assumption(
            slot=a.slot,
            assumed_value=a.assumed_value,
            source=a.source,
            message=a.message,
        )
        for a in result.assumptions
    ]

    district = result.district if result.district in DISTRICTS else None
    if not district:
        memory_district = _memory_value(state, "district")
        if memory_district in DISTRICTS:
            district = memory_district
            assumptions.append(
                _assumption("district", district, f"沿用上一轮区域：{district}", source="session_memory")
            )
        else:
            district = DEFAULT_DISTRICT
            assumptions.append(
                _assumption("district", district, f"未指定区域，默认推荐{district}", source="scene_default")
            )

    budget = result.budget_per_person
    if budget is None or budget <= 0:
        memory_budget = _memory_int(state, "budget_per_person")
        if memory_budget is not None:
            budget = memory_budget
            assumptions.append(
                _assumption("budget_per_person", str(budget), f"沿用上一轮预算：人均 {budget} 元", source="session_memory")
            )
        else:
            budget = DEFAULT_BUDGET
            assumptions.append(
                _assumption("budget_per_person", str(budget), f"未指定预算，默认人均 {budget} 元", source="scene_default")
            )

    # Direct user time expressions are deterministic evidence and must win over
    # an omitted or conflicting structured LLM field.
    minutes = detect_minutes(query) or result.time_budget_minutes
    start_at = (
        detect_start_at(query)
        or _valid_return_by(result.start_at)
        or _valid_return_by(_memory_value(state, "start_at"))
    )
    return_by = detect_return_by(query) or _valid_return_by(result.return_by)
    if minutes is None:
        derived_minutes = derive_time_budget_minutes(start_at, return_by)
        if derived_minutes is not None:
            minutes = derived_minutes
            assumptions.append(
                _assumption(
                    "time_budget_minutes",
                    str(minutes),
                    f"根据 {start_at} 至 {return_by} 计算可用时长：{minutes} 分钟",
                    source="derived_time_window",
                )
            )
    if minutes is None:
        memory_minutes = _memory_int(state, "time_budget_minutes")
        if memory_minutes is not None:
            minutes = memory_minutes
            assumptions.append(
                _assumption("time_budget_minutes", str(minutes), f"沿用上一轮时长：{minutes} 分钟", source="session_memory")
            )
        else:
            minutes = DEFAULT_MINUTES
            assumptions.append(
                _assumption("time_budget_minutes", str(minutes), f"未指定时长，默认 {minutes // 60} 小时行程", source="scene_default")
            )
    elif minutes is not None and minutes <= 0:
        minutes = DEFAULT_MINUTES
        assumptions.append(
            _assumption("time_budget_minutes", str(minutes), f"时长无效，默认 {minutes // 60} 小时行程", source="scene_default")
        )

    queue_tolerance_minutes = detect_queue_tolerance_minutes(query)
    if queue_tolerance_minutes is None:
        queue_tolerance_minutes = result.queue_tolerance_minutes
    if queue_tolerance_minutes is None:
        queue_tolerance_minutes = _memory_int(state, "queue_tolerance_minutes")
    if queue_tolerance_minutes is not None:
        queue_tolerance_minutes = max(0, int(queue_tolerance_minutes))

    poi_count = result.poi_count if result.poi_count and result.poi_count > 0 else DEFAULT_POI_COUNT

    # The structured LLM decision is authoritative for semantic intent. Rules
    # only provide a deterministic fallback when the model returns no usable
    # domain, rather than flattening a nuanced multi-activity request.
    domains = list(dict.fromkeys(result.domains))
    if not domains:
        domains = detect_domains(query)
        assumptions.append(
            _assumption(
                "domains",
                ",".join(d.value for d in domains),
                f"未识别意图域，按 query 推断为 {', '.join(d.value for d in domains)}",
                source="scene_default",
            )
        )

    # Canonical taxonomy extraction protects explicit cuisine wording from an
    # LLM omission, while the LLM remains free to infer preferences when the
    # user only expresses a scene or atmosphere.
    preferred_cuisines = detect_preferred_cuisines(query) or result.preferred_cuisines
    memory_cuisine = _memory_value(state, "preferred_cuisines")
    if preferred_cuisines is None and memory_cuisine:
        preferred_cuisines = [item.strip() for item in memory_cuisine.split(",") if item.strip()] or None
        if preferred_cuisines:
            assumptions.append(
                _assumption(
                    "preferred_cuisines",
                    ",".join(preferred_cuisines),
                    f"沿用上一轮餐饮偏好：{'、'.join(preferred_cuisines)}",
                    source="session_memory",
                )
            )

    constraints = Constraints(
        raw_query=query,
        domains=domains,
        district=district,
        time_budget_minutes=minutes,
        start_at=start_at,
        return_by=return_by,
        queue_tolerance_minutes=queue_tolerance_minutes,
        budget_per_person=budget,
        poi_count=poi_count,
        preferred_cuisines=preferred_cuisines,
        activity_tags=result.activity_tags,
        excluded_categories=(
            detect_excluded_categories(query)
            or [item.strip() for item in (_memory_value(state, "excluded_categories") or "").split(",") if item.strip()]
        ),
    )
    return constraints, _merge_assumptions(assumptions)



async def extract_with_meta(state: GraphState) -> tuple[Constraints, list[Assumption], dict]:
    mode = settings.constraint_extract_mode

    if mode == "rule_only" or not settings.llm_enabled:
        constraints, assumptions = rule_based_extract(state)
        return constraints, assumptions, {"operation": "constraint_extract", "status": "skipped"}

    if not settings.llm_api_key and mode != "rule_only":
        if mode == "llm_only":
            raise LLMError("LLM API key not configured")
        constraints, assumptions = rule_based_extract(state)
        return constraints, assumptions, {"operation": "constraint_extract", "status": "skipped", "fallback_used": True}

    try:
        llm_result, meta = await llm_extract_constraint_with_meta(state)
        constraints, assumptions = normalize_llm_result(llm_result, state["user_query"], state)
        return constraints, assumptions, meta
    except (LLMError, ValidationError) as exc:
        if mode == "llm_only":
            raise
        _ = exc
        constraints, assumptions = rule_based_extract(state)
        return constraints, assumptions, {"operation": "constraint_extract", "status": "failed", "fallback_used": True}


async def extract(state: GraphState) -> tuple[Constraints, list[Assumption]]:
    constraints, assumptions, _meta = await extract_with_meta(state)
    return constraints, assumptions
