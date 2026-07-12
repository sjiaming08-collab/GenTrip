"""Memory context passed into planning nodes."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MemoryContext(BaseModel):
    """Compact session memory payload for a single plan run.

    Priority when filling missing constraints:
    1. Explicit values in the current query.
    2. Current constraints / route / active session state.
    3. Recent turn assumptions.
    4. User profile defaults.
    5. Scene defaults.
    """

    session_id: str
    dialog_summary: str = ""
    current_route: dict[str, Any] | None = None
    current_constraints: dict[str, Any] | None = None
    route_intent: dict[str, Any] | None = None
    assumptions: list[dict[str, Any]] = Field(default_factory=list)
    confirmed_stop_ids: list[str] = Field(default_factory=list)
    rejected_poi_ids: list[str] = Field(default_factory=list)
    recent_turns: list[dict[str, Any]] = Field(default_factory=list)
    user_profile: dict[str, Any] = Field(default_factory=dict)
