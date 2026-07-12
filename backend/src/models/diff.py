"""Diff model for Replan output."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DiffEntry(BaseModel):
    """A single change in a route diff."""

    type: str  # "added" | "removed" | "replaced" | "unchanged"
    sequence: int
    old_poi_name: str | None = None
    new_poi_name: str | None = None
    reason: str = ""


class RoutePlanDiff(BaseModel):
    """Structured diff between original and updated route."""

    original_plan_id: str
    new_plan_id: str
    changes: list[DiffEntry] = Field(default_factory=list)
    summary: str = ""  # e.g. "已将第2站从XX日料替换为YY咖啡，总时长不变"
