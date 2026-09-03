"""约束提取编排 — DeepSeek LLM + 规则降级。"""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from ..config import settings
from ..graph.state import GraphState
from ..llm.constraint_extract_llm import llm_extract_constraint, llm_extract_constraint_with_meta
from ..llm.exceptions import LLMError, failure_meta
from ..llm.schemas import ConstraintExtractResult
from ..models.constraints import Assumption, Constraints, IntentDomain
from .constraint_rules import (
    DEFAULT_BUDGET,
    DEFAULT_MINUTES,
    DEFAULT_POI_COUNT,
    DISTRICTS,
    detect_excluded_categories,
    detect_full_day_expression,
    detect_preferred_cuisines,
    detect_minutes,
    detect_mobility_preferences,
    detect_location_mentions,
    detect_poi_count,
    detect_queue_tolerance_minutes,
    detect_domains,
    detect_start_at,
    detect_return_by,
    derive_time_budget_minutes,
    derive_poi_count,
    has_domain_signal,
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


def _normalized_strings(values: list[str] | None) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in (values or []) if item.strip()))


def _normalized_optional(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _ground_explicit_domains(
    domains: list[IntentDomain],
    query: str,
) -> list[IntentDomain]:
    """Drop model-added domains when the same query has grounded domains.

    The LLM can still recognize niche intents missing from the small keyword
    taxonomy: when there is no overlap, its semantic decision is preserved.
    When an overlap does exist, unrelated additions such as interpreting the
    generic word ``玩`` as both sightseeing and leisure must not become hard
    route requirements.
    """

    detected = set(detect_domains(query))
    grounded = [domain for domain in domains if domain in detected]
    if grounded:
        return grounded
    # If the deterministic taxonomy sees an explicit generic signal such as
    # "玩", it is authoritative about what that signal cannot mean. Unknown
    # niche activities still remain LLM-owned when rules see no signal at all.
    return list(detected) if has_domain_signal(query) else domains


def _evidenced_explicit(
    result: ConstraintExtractResult,
    field: str,
    query: str,
) -> Any:
    """Return a current-turn field only when its v2 evidence is trustworthy.

    Contract v1 is accepted during rollout so stored fixtures and older provider
    responses remain readable. Contract v2 must point back to an exact query
    substring; unsupported model inferences are discarded before memory/default
    resolution.
    """

    value = getattr(result, field)
    is_empty = value is None or value == "" or value == []
    if result.contract_version < 2 or is_empty:
        return value
    evidence = (result.evidence.get(field) or "").strip()
    if evidence and evidence in query:
        return value
    return [] if isinstance(value, list) else None


def normalize_llm_result(
    result: ConstraintExtractResult,
    query: str,
    state: GraphState | None = None,
) -> tuple[Constraints, list[Assumption]]:
    state = state or GraphState(user_query=query)
    # LLM-owned assumptions were the main source of conflicting defaults. The
    # resolver is now the sole owner of memory/default/derived assumptions.
    assumptions: list[Assumption] = []

    location_mentions = _normalized_strings(
        _evidenced_explicit(result, "location_mentions_explicit", query)
    )
    valid_geo_mentions = [
        item for item in result.geo_mentions
        if item.evidence and item.evidence in query and item.text in query
    ]
    if result.contract_version >= 3 and valid_geo_mentions:
        location_mentions = _normalized_strings([item.text for item in valid_geo_mentions])
    if not location_mentions:
        location_mentions = detect_location_mentions(query)
    city = _normalized_optional(_evidenced_explicit(result, "city_explicit", query))
    district = _normalized_optional(
        _evidenced_explicit(result, "district_explicit", query)
    )
    current_query_has_geo = bool(location_mentions or city or district)

    # A new place expression must not inherit the previous turn's geography.
    # Without a new expression, session geography remains useful for follow-ups.
    if not current_query_has_geo:
        memory_locations = _memory_value(state, "location_mentions")
        if memory_locations:
            location_mentions = _normalized_strings(memory_locations.split(","))
        city = _normalized_optional(_memory_value(state, "city"))
        district = _normalized_optional(_memory_value(state, "district"))
        if city:
            assumptions.append(
                _assumption("city", city, f"沿用上一轮城市：{city}", source="session_memory")
            )
        if district:
            assumptions.append(
                _assumption("district", district, f"沿用上一轮区域：{district}", source="session_memory")
            )

    if district in DISTRICTS and not city:
        city = "上海市"

    if (
        not location_mentions
        and not city
        and not district
        and (state.get("user_lat") is None or state.get("user_lng") is None)
    ):
        city = settings.amap_city or "上海"
        assumptions.append(
            _assumption("city", city, f"未指定地点，默认在{city}检索", source="scene_default")
        )

    budget = _evidenced_explicit(result, "budget_per_person_explicit", query)
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
    v3_time = result.time_expression if result.contract_version >= 3 else None
    is_full_day = bool(
        detect_full_day_expression(query)
        or (
            v3_time
            and v3_time.kind == "full_day"
            and v3_time.evidence
            and v3_time.evidence in query
        )
    )
    minutes = None if is_full_day else (
        detect_minutes(query) or _evidenced_explicit(
            result, "time_budget_minutes_explicit", query
        )
    )
    start_at = (
        detect_start_at(query)
        or (v3_time.start_at if v3_time and v3_time.evidence and v3_time.evidence in query else None)
        or _valid_return_by(_evidenced_explicit(result, "start_at_explicit", query))
        or _valid_return_by(_memory_value(state, "start_at"))
    )
    return_by = (
        detect_return_by(query)
        or (v3_time.return_by if v3_time and v3_time.evidence and v3_time.evidence in query else None)
        or _valid_return_by(_evidenced_explicit(result, "return_by_explicit", query))
    )
    if minutes is None and not is_full_day:
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
    if minutes is None and not is_full_day:
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
        queue_tolerance_minutes = _evidenced_explicit(
            result, "queue_tolerance_minutes_explicit", query
        )
    if queue_tolerance_minutes is None:
        queue_tolerance_minutes = _memory_int(state, "queue_tolerance_minutes")
    if queue_tolerance_minutes is not None:
        queue_tolerance_minutes = max(0, int(queue_tolerance_minutes))

    suggested_poi_count = (
        _evidenced_explicit(result, "anchor_count_explicit", query)
        or DEFAULT_POI_COUNT
    )
    explicit_anchor_count = detect_poi_count(query) or _evidenced_explicit(
        result, "anchor_count_explicit", query
    )
    poi_count = derive_poi_count(
        query,
        minutes,
        suggested_count=suggested_poi_count,
    )
    if detect_poi_count(query) is None and poi_count != suggested_poi_count:
        assumptions.append(
            _assumption(
                "poi_count",
                str(poi_count),
                f"按 {minutes} 分钟行程安排 {poi_count} 站",
                source="duration_derived",
            )
        )

    # The structured LLM decision is authoritative for semantic intent. Rules
    # only provide a deterministic fallback when the model returns no usable
    # domain, rather than flattening a nuanced multi-activity request.
    domains = list(
        dict.fromkeys(_evidenced_explicit(result, "domains_explicit", query) or [])
    )
    if domains:
        domains = _ground_explicit_domains(domains, query)
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
    preferred_cuisines = detect_preferred_cuisines(query) or _evidenced_explicit(
        result, "preferred_cuisines_explicit", query
    )
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

    llm_excluded = _normalized_strings(
        _evidenced_explicit(result, "excluded_categories_explicit", query)
    )
    explicit_excluded = _normalized_strings(
        [*detect_excluded_categories(query), *llm_excluded]
    )
    if explicit_excluded:
        excluded_categories = explicit_excluded
    else:
        excluded_categories = _normalized_strings(
            (_memory_value(state, "excluded_categories") or "").split(",")
        )

    explicit_activities = [
        item.model_dump(mode="json")
        for item in result.activities
        if item.evidence
        and item.evidence in query
        and item.text.strip() not in {"玩", "逛", "逛逛", "活动"}
        and item.evidence.strip() not in {"玩", "逛", "逛逛", "玩一天", "玩一整天", "全天"}
    ] if result.contract_version >= 3 else []
    geo_relation = (
        valid_geo_mentions[0].relation
        if valid_geo_mentions
        else (
            "nearby"
            if location_mentions and any(word in query for word in ("附近", "周边"))
            else None
        )
    )

    constraints = Constraints(
        raw_query=query,
        domains=domains,
        city=city,
        district=district,
        time_budget_minutes=minutes,
        start_at=start_at,
        return_by=return_by,
        queue_tolerance_minutes=queue_tolerance_minutes,
        budget_per_person=budget,
        poi_count=poi_count,
        anchor_count_explicit=explicit_anchor_count,
        poi_count_min=(poi_count if explicit_anchor_count else max(1, poi_count - 1)),
        poi_count_target=poi_count,
        poi_count_max=min(8, poi_count if explicit_anchor_count else poi_count + 2),
        preferred_cuisines=preferred_cuisines,
        activity_tags=_evidenced_explicit(result, "activity_tags_explicit", query),
        location_mentions=location_mentions,
        excluded_categories=excluded_categories,
        sequence_preferences=_normalized_strings(
            _evidenced_explicit(result, "sequence_preferences_explicit", query)
        ),
        scene_type=_normalized_optional(
            _evidenced_explicit(result, "scene_type_explicit", query)
        ),
        pace=_normalized_optional(_evidenced_explicit(result, "pace_explicit", query)),
        mobility_preferences=(
            detect_mobility_preferences(query)
            or _normalized_strings(
                _evidenced_explicit(result, "mobility_preferences_explicit", query)
            )
        ),
        time_expression_kind=(
            "full_day" if is_full_day else (
                v3_time.kind if v3_time and v3_time.kind != "none" else "unspecified"
            )
        ),
        geo_relation=geo_relation,
        explicit_activities=explicit_activities,
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
        return constraints, assumptions, {
            **meta,
            "turn_decision": {
                "turn_mode": llm_result.turn_mode,
                "primary_intent": llm_result.primary_intent,
                "query_understanding": llm_result.query_understanding,
            },
        }
    except (LLMError, ValidationError) as exc:
        if mode == "llm_only":
            raise
        constraints, assumptions = rule_based_extract(state)
        return constraints, assumptions, failure_meta("constraint_extract", exc)


async def extract(state: GraphState) -> tuple[Constraints, list[Assumption]]:
    constraints, assumptions, _meta = await extract_with_meta(state)
    return constraints, assumptions
