"""Optional LLM judge for subjective route quality dimensions."""

from __future__ import annotations

import json
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, model_validator

from ..llm.client import DeepSeekClient


class JudgeClient(Protocol):
    async def chat_json_with_meta(
        self, system: str, user: str, *, operation: str, temperature: float
    ) -> tuple[dict[str, Any], dict[str, Any]]: ...


class JudgeScores(BaseModel):
    requirement_satisfaction: int = Field(ge=0, le=5)
    instruction_following: int = Field(ge=0, le=5)
    poi_grounding: int = Field(ge=0, le=5)
    route_coherence: int = Field(ge=0, le=5)
    explanation_quality: int = Field(ge=0, le=5)


class RouteJudgeResult(BaseModel):
    verdict: Literal["pass", "fail"]
    scores: JudgeScores
    hard_constraint_violations: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1, max_length=1000)
    model_meta: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def hard_violations_must_fail(self) -> "RouteJudgeResult":
        if self.hard_constraint_violations and self.verdict != "fail":
            raise ValueError("a hard-constraint violation requires verdict=fail")
        return self

    @property
    def normalized_score(self) -> float:
        values = list(self.scores.model_dump().values())
        return round(sum(values) / (len(values) * 5), 3)


SYSTEM_PROMPT = """You evaluate travel plans. Judge only from the supplied request, expected constraints, planner output, and POI evidence.
Hard constraints include exclusions, budget ceilings, time windows, requested area, accessibility, and required activities. A hard-constraint violation must produce verdict=fail.
Score each dimension from 0 to 5. Do not reward fluent wording when the route is unsupported or infeasible. Return one JSON object matching the requested schema."""


class RouteJudge:
    def __init__(self, client: JudgeClient | None = None) -> None:
        self._client = client or DeepSeekClient()

    async def evaluate(self, case: dict[str, Any], deterministic_result: dict[str, Any]) -> RouteJudgeResult:
        payload = {
            "request": case.get("query"),
            "expected": case.get("expect") or {},
            "deterministic_evidence": deterministic_result,
            "response_schema": {
                "verdict": "pass|fail",
                "scores": {
                    "requirement_satisfaction": "0..5",
                    "instruction_following": "0..5",
                    "poi_grounding": "0..5",
                    "route_coherence": "0..5",
                    "explanation_quality": "0..5",
                },
                "hard_constraint_violations": ["short machine-readable reason"],
                "rationale": "concise evidence-based explanation",
            },
        }
        raw, meta = await self._client.chat_json_with_meta(
            SYSTEM_PROMPT,
            json.dumps(payload, ensure_ascii=False, default=str),
            operation="route_quality_judge",
            temperature=0.0,
        )
        return RouteJudgeResult.model_validate({**raw, "model_meta": meta})
