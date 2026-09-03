"""约束与假设模型。"""

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class IntentDomain(str, Enum):
    DINING = "dining"
    SIGHTSEEING = "sightseeing"
    SHOPPING = "shopping"
    LEISURE = "leisure"


class ConstraintStrength(str, Enum):
    HARD = "hard"
    SOFT = "soft"
    POLICY = "policy"


class ConstraintAtom(BaseModel):
    constraint_id: str
    field: str
    operator: str = "equals"
    value: Any
    strength: ConstraintStrength
    source: Literal["user", "memory", "derived", "scene", "default"]
    evidence: str | None = None
    priority: int = Field(default=50, ge=0, le=100)
    overridable: bool = True
    relax_policy: str | None = None


class ScheduleEnvelope(BaseModel):
    time_scope: Literal["exact_duration", "clock_window", "daypart", "full_day", "unspecified"]
    earliest_start: str | None = None
    latest_end: str | None = None
    min_duration_minutes: int = Field(ge=1)
    target_duration_minutes: int = Field(ge=1)
    max_duration_minutes: int = Field(ge=1)
    flexibility: Literal["hard", "soft"]
    source: Literal["user", "derived", "policy", "memory", "default"]


class CompiledConstraints(BaseModel):
    contract_version: Literal[3] = 3
    atoms: list[ConstraintAtom] = Field(default_factory=list)
    schedule_envelope: ScheduleEnvelope
    search_domains: list[IntentDomain] = Field(default_factory=list)
    active_policies: list[dict] = Field(default_factory=list)
    dropped_policies: list[dict] = Field(default_factory=list)


class Assumption(BaseModel):
    slot: str
    assumed_value: str
    source: str
    message: str
    overridable: bool = True


class Constraints(BaseModel):
    raw_query: str
    domains: list[IntentDomain] = Field(min_length=1)
    city: Optional[str] = None
    district: Optional[str] = None
    time_budget_minutes: Optional[int] = None
    start_at: Optional[str] = None
    return_by: Optional[str] = None
    queue_tolerance_minutes: Optional[int] = None
    budget_per_person: int
    poi_count: int = 3
    # ``poi_count`` remains the backward-compatible route target. The fields
    # below distinguish user-requested anchor activities from service slots
    # (meal/rest) inserted by the blueprint policy.
    anchor_count_explicit: Optional[int] = None
    poi_count_min: Optional[int] = None
    poi_count_target: Optional[int] = None
    poi_count_max: Optional[int] = None
    preferred_cuisines: Optional[list[str]] = None
    activity_tags: Optional[list[str]] = None
    location_mentions: list[str] = Field(default_factory=list)
    excluded_categories: list[str] = Field(default_factory=list)
    sequence_preferences: list[str] = Field(default_factory=list)
    scene_type: Optional[str] = None
    pace: Optional[str] = None
    mobility_preferences: list[str] = Field(default_factory=list)
    time_expression_kind: Literal[
        "exact_duration", "clock_window", "daypart", "full_day", "unspecified"
    ] = "unspecified"
    time_budget_hard: bool = False
    schedule_envelope: Optional[ScheduleEnvelope] = None
    geo_relation: Literal["exact", "nearby", "within_area"] | None = None
    explicit_activities: list[dict] = Field(default_factory=list)
