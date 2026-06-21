"""路线相关模型。"""

from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


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


class RouteStop(BaseModel):
    sequence: int
    poi_id: str
    poi_name: str
    category: str
    arrival_time: str
    departure_time: str
    visit_duration_min: int
    travel_time_from_prev_min: int = 0


class RoutePlan(BaseModel):
    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    plan_name: str
    summary: str
    stops: list[RouteStop]
    total_duration_min: int
    estimated_cost_per_person: int


class ValidationReport(BaseModel):
    route_id: str
    feasible: bool
    violations: list[str] = Field(default_factory=list)


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
