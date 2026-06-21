"""LLM 结构化输出 schema。"""

from pydantic import BaseModel, Field

from ..models.constraints import IntentDomain


class LlmAssumption(BaseModel):
    slot: str
    assumed_value: str
    message: str
    source: str = "llm_inferred"


class ConstraintExtractResult(BaseModel):
    domains: list[IntentDomain] = Field(default_factory=list)
    district: str | None = None
    time_budget_minutes: int | None = None
    return_by: str | None = None
    budget_per_person: int | None = None
    poi_count: int | None = None
    preferred_cuisines: list[str] | None = None
    activity_tags: list[str] | None = None
    assumptions: list[LlmAssumption] = Field(default_factory=list)
