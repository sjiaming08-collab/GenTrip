"""Agent reply envelope models."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ReplyType(str, Enum):
    ROUTE = "route"
    MULTI_ROUTE = "multi_route"
    DIFF = "diff"
    DEGRADED_ROUTE = "degraded_route"
    REJECT = "reject"


class AgentReplyMeta(BaseModel):
    plan_path: str | None = None
    assumptions: list[dict[str, Any]] = Field(default_factory=list)
    relaxed_constraints: list[str] = Field(default_factory=list)
    degraded: bool = False
    next_suggested_user_moves: list[str] = Field(default_factory=list)


class AgentReply(BaseModel):
    reply_type: ReplyType
    structured: list[dict[str, Any]] = Field(default_factory=list)
    presentation: dict[str, Any] | None = None
    meta: AgentReplyMeta
