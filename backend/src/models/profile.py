"""User profile — long-term preferences mined from session history."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class UserProfile(BaseModel):
    """Long-term user preferences mined from constraint history.

    Mined deterministically (no LLM) from SessionState.constraint_history.
    Used as Priority 4 in constraint completion.
    """

    user_id: str

    # ---- regional preferences (frequency-sorted) ----
    preferred_districts: list[str] = Field(default_factory=list)

    # ---- category preferences ----
    preferred_cuisines: list[str] = Field(default_factory=list)
    preferred_activity_tags: list[str] = Field(default_factory=list)

    # ---- numeric preferences (moving average) ----
    avg_budget_per_person: int = 150
    avg_time_budget_minutes: int = 180
    avg_poi_count: int = 3

    # ---- time preferences ----
    common_return_by: str | None = None

    # ---- scenario preferences ----
    favorite_scenarios: list[str] = Field(default_factory=list)

    # ---- POI-level preferences ----
    liked_poi_ids: list[str] = Field(default_factory=list)
    avoided_poi_ids: list[str] = Field(default_factory=list)

    # ---- stats ----
    total_sessions: int = 0
    total_turns: int = 0
    last_active_ts: str = ""
    created_ts: str = ""
    updated_ts: str = ""

    @classmethod
    def create_default(cls, user_id: str) -> "UserProfile":
        now = datetime.now(timezone.utc).isoformat()
        return cls(user_id=user_id, created_ts=now, updated_ts=now)
