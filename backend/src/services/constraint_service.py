"""约束提取编排 — DeepSeek LLM + 规则降级。"""

from __future__ import annotations

import re

from pydantic import ValidationError

from ..config import settings
from ..graph.state import GraphState
from ..llm.constraint_extract_llm import llm_extract_constraint
from ..llm.exceptions import LLMError
from ..llm.schemas import ConstraintExtractResult
from ..models.constraints import Assumption, Constraints
from .constraint_rules import (
    DEFAULT_BUDGET,
    DEFAULT_DISTRICT,
    DEFAULT_MINUTES,
    DEFAULT_POI_COUNT,
    DISTRICTS,
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


def _default_assumption(slot: str, value: str, message: str) -> Assumption:
    return Assumption(
        slot=slot,
        assumed_value=value,
        source="scene_default",
        message=message,
    )


def normalize_llm_result(
    result: ConstraintExtractResult,
    query: str,
) -> tuple[Constraints, list[Assumption]]:
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
        district = DEFAULT_DISTRICT
        assumptions.append(
            _default_assumption(
                "district",
                district,
                f"未指定区域，默认推荐{district}",
            )
        )

    budget = result.budget_per_person
    if budget is None or budget <= 0:
        budget = DEFAULT_BUDGET
        assumptions.append(
            _default_assumption(
                "budget_per_person",
                str(budget),
                f"未指定预算，默认人均 {budget} 元",
            )
        )

    minutes = result.time_budget_minutes
    return_by = _valid_return_by(result.return_by)
    if minutes is None and return_by is None:
        minutes = DEFAULT_MINUTES
        assumptions.append(
            _default_assumption(
                "time_budget_minutes",
                str(minutes),
                f"未指定时长，默认 {minutes // 60} 小时行程",
            )
        )
    elif minutes is not None and minutes <= 0:
        minutes = DEFAULT_MINUTES
        assumptions.append(
            _default_assumption(
                "time_budget_minutes",
                str(minutes),
                f"时长无效，默认 {minutes // 60} 小时行程",
            )
        )

    poi_count = result.poi_count if result.poi_count and result.poi_count > 0 else DEFAULT_POI_COUNT

    constraints = Constraints(
        raw_query=query,
        purpose=result.purpose,
        district=district,
        time_budget_minutes=minutes,
        return_by=return_by,
        budget_per_person=budget,
        poi_count=poi_count,
        preferred_cuisines=result.preferred_cuisines,
        activity_tags=result.activity_tags,
    )
    return constraints, _merge_assumptions(assumptions)


async def extract(state: GraphState) -> tuple[Constraints, list[Assumption]]:
    mode = settings.constraint_extract_mode

    if mode == "rule_only" or not settings.llm_enabled:
        return rule_based_extract(state)

    if not settings.llm_api_key and mode != "rule_only":
        if mode == "llm_only":
            raise LLMError("LLM API key 未配置")
        return rule_based_extract(state)

    try:
        llm_result = await llm_extract_constraint(state)
        return normalize_llm_result(llm_result, state["user_query"])
    except (LLMError, ValidationError) as exc:
        if mode == "llm_only":
            raise
        _ = exc
        return rule_based_extract(state)
