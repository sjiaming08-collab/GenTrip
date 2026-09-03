"""Semantic activity blueprints produced before POI retrieval."""

from typing import Literal

from pydantic import BaseModel, Field

from .constraints import IntentDomain


class SlotTimeWindow(BaseModel):
    start: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    end: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class ActivitySlot(BaseModel):
    slot_id: str
    role: Literal["anchor", "meal", "rest", "optional"]
    required: bool = True
    domain: IntentDomain | None = None
    categories: list[str] = Field(default_factory=list)
    activity_tags: list[str] = Field(default_factory=list)
    time_window: SlotTimeWindow | None = None
    duration_minutes: int = Field(default=60, ge=15, le=240)
    duration_min_minutes: int | None = Field(default=None, ge=15, le=240)
    duration_max_minutes: int | None = Field(default=None, ge=15, le=240)
    spatial_policy: Literal["near_anchor", "near_previous"] = "near_previous"
    source: Literal["explicit", "inferred", "policy"] = "inferred"
    requirement_level: Literal["hard", "policy", "optional"] | None = None
    order_policy: Literal["fixed", "flexible"] = "flexible"
    expected_time_window: SlotTimeWindow | None = None
    assumption_message: str | None = None


class ItineraryBlueprint(BaseModel):
    blueprint_id: str
    style: Literal["balanced", "experiential"]
    scene_type: Literal["solo", "couple", "friends", "family"] = "solo"
    start_at: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    return_by: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    slots: list[ActivitySlot] = Field(default_factory=list, max_length=8)


class ActivitySlotDraft(BaseModel):
    """Compact LLM-owned semantics; deterministic compilation fills policy fields."""

    slot_id: str
    role: Literal["anchor", "optional"] = "anchor"
    domain: IntentDomain | None = None
    categories: list[str] = Field(min_length=1)
    activity_tags: list[str] = Field(default_factory=list)
    time_window: SlotTimeWindow | None = None
    duration_minutes: int = Field(default=60, ge=15, le=240)
    spatial_policy: Literal["near_anchor", "near_previous"] = "near_previous"


class ItineraryBlueprintDraft(BaseModel):
    style: Literal["balanced", "experiential"]
    slots: list[ActivitySlotDraft] = Field(min_length=1, max_length=6)


class BlueprintDrafts(BaseModel):
    blueprints: list[ItineraryBlueprintDraft] = Field(min_length=1, max_length=2)
