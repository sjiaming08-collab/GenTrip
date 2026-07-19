"""Planner V2 decision and feasibility models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


PlanningOutcome = Literal[
    "pending",
    "route_ready",
    "marginal",
    "clarification_required",
    "infeasible",
    "no_candidate",
    "change_applied",
    "awaiting_choice",
    "change_rejected",
    "rejected",
]


class DurationEstimate(BaseModel):
    optimistic_minutes: int
    expected_minutes: int
    conservative_minutes: int
    available_minutes: int | None = None
    buffer_minutes: int = 0
    confidence: Literal["low", "medium", "high"] = "medium"


class PlanningOption(BaseModel):
    action: str
    label: str
    data: dict[str, Any] = Field(default_factory=dict)


class PlanningDecision(BaseModel):
    status: Literal["ready", "marginal", "clarification_required", "infeasible"]
    outcome: PlanningOutcome
    estimate: DurationEstimate
    reasons: list[str] = Field(default_factory=list)
    options: list[PlanningOption] = Field(default_factory=list)


class RouteJudgement(BaseModel):
    route_id: str
    feasible: bool
    hard_violations: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    optimistic_duration_min: int
    expected_duration_min: int
    conservative_duration_min: int
    estimated_cost_per_person: int
