"""LLM scoring for candidate routes."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from ..config import settings
from ..models.route import RoutePlan
from .client import get_llm_client
from .exceptions import LLMError, failure_meta
from .prompts.route_evaluate import SYSTEM_PROMPT


class LlmRouteScore(BaseModel):
    plan_id: str
    execution: float = Field(ge=0.0, le=1.0)
    quality: float = Field(ge=0.0, le=1.0)
    preference: float = Field(ge=0.0, le=1.0)
    comment: str = ""


class LlmRouteScoreResult(BaseModel):
    scores: list[LlmRouteScore] = Field(default_factory=list)


def _route_payload(route: RoutePlan) -> dict[str, Any]:
    return {
        "plan_id": route.plan_id,
        "plan_name": route.plan_name,
        "summary": route.summary,
        "total_duration_min": route.total_duration_min,
        "estimated_cost_per_person": route.estimated_cost_per_person,
        "stops": [
            {
                "name": stop.poi_name,
                "category": stop.category,
                "arrival_time": stop.arrival_time,
                "departure_time": stop.departure_time,
                "travel_time_from_prev_min": stop.travel_time_from_prev_min,
            }
            for stop in route.stops
        ],
    }


async def llm_score_routes_with_meta(
    routes: list[RoutePlan],
    *,
    constraints: dict,
    user_query: str,
    memory_context: dict | None = None,
) -> tuple[dict[str, LlmRouteScore], dict]:
    if not settings.llm_enabled or not settings.llm_api_key:
        return {}, {"operation": "route_evaluate", "status": "skipped"}
    if not routes:
        return {}, {"operation": "route_evaluate", "status": "skipped"}

    payload = {
        "user_query": user_query,
        "constraints": constraints,
        "dialog_summary": (memory_context or {}).get("dialog_summary", ""),
        "routes": [_route_payload(route) for route in routes],
    }
    try:
        client = get_llm_client()
        if hasattr(client, "chat_json_with_meta"):
            raw, meta = await client.chat_json_with_meta(
                SYSTEM_PROMPT,
                json.dumps(payload, ensure_ascii=False),
                operation="route_evaluate",
            )
        else:
            raw = await client.chat_json(SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False))
            meta = {"operation": "route_evaluate", "status": "success"}
        result = LlmRouteScoreResult.model_validate(raw)
    except (LLMError, ValidationError) as exc:
        return {}, failure_meta("route_evaluate", exc)

    by_id: dict[str, LlmRouteScore] = {}
    for score in result.scores:
        by_id[score.plan_id] = score
    return by_id, meta


async def llm_score_routes(
    routes: list[RoutePlan],
    *,
    constraints: dict,
    user_query: str,
    memory_context: dict | None = None,
) -> dict[str, LlmRouteScore]:
    scores, _meta = await llm_score_routes_with_meta(
        routes,
        constraints=constraints,
        user_query=user_query,
        memory_context=memory_context,
    )
    return scores
