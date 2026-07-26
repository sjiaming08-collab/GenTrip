"""Session state for multi-turn planning."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class RouteIntent(BaseModel):
    """Structured summary of the user's route-planning intent."""

    intent_type: str
    primary_intent: str
    secondary_intents: list[str] = Field(default_factory=list)
    query_understanding: str = ""


class Turn(BaseModel):
    """One conversational turn stored in a session."""

    turn_id: str
    user_query: str
    reply_type: str
    route_results: list[dict[str, Any]] = Field(default_factory=list)
    assumptions: list[dict[str, Any]] = Field(default_factory=list)
    presentation: dict[str, Any] | None = None
    assistant_message: str = ""
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SessionState(BaseModel):
    """Cross-turn state persisted by session_id."""

    session_id: str
    tenant_id: str = "default"
    user_id: str | None = None
    title: str = ""
    version: int = 0
    turn_count: int = 0
    mode: str = "planning"
    route_intent: RouteIntent | None = None
    assumptions: list[dict[str, Any]] = Field(default_factory=list)
    current_route: dict[str, Any] | None = None
    current_constraints: dict[str, Any] | None = None
    confirmed_stop_ids: list[str] = Field(default_factory=list)
    rejected_poi_ids: list[str] = Field(default_factory=list)
    overridden_slots: list[str] = Field(default_factory=list)
    route_feedback: list[dict[str, Any]] = Field(default_factory=list)
    dialog_summary: str = ""
    recent_turns: list[Turn] = Field(default_factory=list)
    memory_facts: list[dict[str, Any]] = Field(default_factory=list)
    latest_response: dict[str, Any] | None = None
    pending_change: dict[str, Any] | None = None
    rejected_change: dict[str, Any] | None = None

    def add_turn(self, turn: Turn) -> None:
        self.recent_turns.append(turn)
        if len(self.recent_turns) > 5:
            self.recent_turns = self.recent_turns[-5:]
        self.turn_count += 1
