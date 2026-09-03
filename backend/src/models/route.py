"""路线相关模型。"""

from enum import Enum
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class RouteSource(str, Enum):
    BUNDLE_HIT = "BUNDLE_HIT"
    BUNDLE_ADAPTED = "BUNDLE_ADAPTED"
    COLD_GENERATED = "COLD_GENERATED"
    DEGRADED = "DEGRADED"


class ScoredPoi(BaseModel):
    poi_id: str
    name: str
    category: str
    district: str
    lat: float
    lng: float
    rating: float
    price_per_person: int
    composite_score: float = 0.0
    dimension: Optional[str] = None
    queue_wait_min: int = 0
    opening_hours: list[dict] = Field(default_factory=list)
    opening_hours_text: Optional[str] = None
    ugc_summary: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    match_reasons: list[str] = Field(default_factory=list)
    slot_id: Optional[str] = None
    blueprint_id: Optional[str] = None
    slot_role: Optional[str] = None
    slot_source: Optional[str] = None
    slot_required: bool = True
    slot_duration_minutes: Optional[int] = None
    slot_time_window: Optional[dict] = None
    slot_expected_time_window: Optional[dict] = None
    recall_keywords: list[str] = Field(default_factory=list)
    provider: Optional[str] = None
    field_sources: dict[str, str] = Field(default_factory=dict)
    match_explanation: Optional[str] = None


class RouteLeg(BaseModel):
    from_poi_id: str
    to_poi_id: str
    mode: Literal["walking", "cycling", "transit", "driving"]
    distance_m: int = Field(ge=0)
    duration_min: int = Field(ge=0)
    cost_per_person: int = Field(default=0, ge=0)
    source: str
    estimated: bool = True
    confidence: Literal["low", "medium", "high"] = "medium"
    fallback_used: bool = False
    selection_reason: str


class RouteStop(BaseModel):
    sequence: int
    poi_id: str
    poi_name: str
    category: str
    arrival_time: str
    departure_time: str
    visit_duration_min: int
    travel_time_from_prev_min: int = 0
    travel_source: str = "mock_haversine"
    travel_estimated: bool = True
    travel_time_lower_bound_min: int = 0
    travel_time_upper_bound_min: int = 0
    travel_confidence: str = "medium"
    queue_wait_min: int = 0
    opening_hours_text: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    slot_id: Optional[str] = None
    slot_role: Optional[str] = None
    slot_source: Optional[str] = None
    slot_time_window: Optional[dict] = None


class RoutePlan(BaseModel):
    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    plan_name: str
    summary: str
    stops: list[RouteStop]
    total_duration_min: int
    estimated_cost_per_person: int
    legs: list[RouteLeg] = Field(default_factory=list)
    blueprint_id: Optional[str] = None
    style: Optional[str] = None

    @model_validator(mode="after")
    def hydrate_legacy_legs(self) -> "RoutePlan":
        """Keep old cached routes API-compatible while new routes emit full legs."""

        if self.legs or len(self.stops) < 2:
            return self
        self.legs = [
            RouteLeg(
                from_poi_id=previous.poi_id,
                to_poi_id=current.poi_id,
                mode="walking",
                distance_m=0,
                duration_min=current.travel_time_from_prev_min,
                source=current.travel_source,
                estimated=current.travel_estimated,
                confidence=current.travel_confidence if current.travel_confidence in {"low", "medium", "high"} else "medium",
                fallback_used=current.travel_estimated,
                selection_reason="由旧版站点交通字段兼容回填",
            )
            for previous, current in zip(self.stops, self.stops[1:])
        ]
        return self


class ValidationReport(BaseModel):
    route_id: str
    feasible: bool
    violations: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    optimistic_duration_min: Optional[int] = None
    expected_duration_min: Optional[int] = None
    conservative_duration_min: Optional[int] = None


class ScoredRoute(BaseModel):
    route: RoutePlan
    execution_score: float
    quality_score: float
    preference_score: float
    final_score: float
    rank: int = 0


class RouteScores(BaseModel):
    execution: float
    quality: float
    final: float


class RoutePlanResult(BaseModel):
    route: RoutePlan
    source: RouteSource = RouteSource.COLD_GENERATED
    bundle_id: Optional[str] = None
    rank: int
    scores: RouteScores


class Presentation(BaseModel):
    title: str
    summary: str
    highlights: list[str] = Field(default_factory=list)
