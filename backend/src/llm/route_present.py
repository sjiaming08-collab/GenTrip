"""LLM presentation copy for final route replies."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from ..config import settings
from ..models.route import Presentation, RoutePlanResult
from .client import get_llm_client
from .exceptions import LLMError

SYSTEM_PROMPT = """你是 GenTrip 的路线推荐文案助手。
生成面向用户的中文推荐文案，标题必须以「为您推荐」开头。
文案要具体、自然、简洁，不编造候选路线中不存在的地点。
只输出 JSON：{"title":"...","summary":"...","highlights":["..."]}。
"""


class LlmPresentation(BaseModel):
    title: str
    summary: str
    highlights: list[str] = Field(default_factory=list)


def _result_payload(result: RoutePlanResult) -> dict[str, Any]:
    route = result.route
    return {
        "plan_name": route.plan_name,
        "summary": route.summary,
        "total_duration_min": route.total_duration_min,
        "estimated_cost_per_person": route.estimated_cost_per_person,
        "scores": result.scores.model_dump(mode="json"),
        "stops": [
            {
                "name": stop.poi_name,
                "category": stop.category,
                "arrival_time": stop.arrival_time,
                "departure_time": stop.departure_time,
            }
            for stop in route.stops
        ],
    }



async def llm_present_route_with_meta(
    results: list[RoutePlanResult],
    *,
    user_query: str,
    assumptions: list[dict],
    relaxed_constraints: list[str],
    evaluation_meta: dict | None = None,
) -> tuple[Presentation | None, dict]:
    if not settings.llm_enabled or not settings.llm_api_key or not results:
        return None, {"operation": "route_present", "status": "skipped"}

    payload = {
        "user_query": user_query,
        "best_route": _result_payload(results[0]),
        "alternative_count": max(0, len(results) - 1),
        "assumptions": assumptions,
        "relaxed_constraints": relaxed_constraints,
        "evaluation_meta": evaluation_meta or {},
    }
    try:
        client = get_llm_client()
        if hasattr(client, "chat_json_with_meta"):
            raw, meta = await client.chat_json_with_meta(
                SYSTEM_PROMPT,
                json.dumps(payload, ensure_ascii=False),
                operation="route_present",
            )
        else:
            raw = await client.chat_json(SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False))
            meta = {"operation": "route_present", "status": "success"}
        data = LlmPresentation.model_validate(raw)
    except (LLMError, ValidationError):
        return None, {"operation": "route_present", "status": "failed", "fallback_used": True}

    title = data.title.strip()
    if not title.startswith("\u4e3a\u60a8\u63a8\u8350"):
        title = f"\u4e3a\u60a8\u63a8\u8350{title}"
    return Presentation(
        title=title,
        summary=data.summary.strip(),
        highlights=data.highlights[:4],
    ), meta


async def llm_present_route(
    results: list[RoutePlanResult],
    *,
    user_query: str,
    assumptions: list[dict],
    relaxed_constraints: list[str],
    evaluation_meta: dict | None = None,
) -> Presentation | None:
    presentation, _meta = await llm_present_route_with_meta(
        results,
        user_query=user_query,
        assumptions=assumptions,
        relaxed_constraints=relaxed_constraints,
        evaluation_meta=evaluation_meta,
    )
    return presentation
