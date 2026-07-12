"""API DTO。"""

from typing import Optional

from pydantic import BaseModel, Field


class PlanRequest(BaseModel):
    query: str = Field(min_length=1)
    user_id: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    session_id: Optional[str] = None


class AgentReplyMetaResponse(BaseModel):
    plan_path: Optional[str] = None
    assumptions: list[dict] = Field(default_factory=list)
    relaxed_constraints: list[str] = Field(default_factory=list)
    degraded: bool = False
    next_suggested_user_moves: list[str] = Field(default_factory=list)
    phase_log: list[dict] = Field(default_factory=list)
    llm_calls: list[dict] = Field(default_factory=list)
    token_usage: dict = Field(default_factory=dict)
    debug_trace_id: Optional[str] = None


class PlanResponse(BaseModel):
    run_id: str
    run_status: str
    plan_path: Optional[str]
    assumptions: list[dict]
    route_results: list[dict]
    presentation: Optional[dict]
    current_phase: str
    session_id: Optional[str] = None
    reply_type: str = "route"
    structured: list[dict] = Field(default_factory=list)
    meta: AgentReplyMetaResponse = Field(default_factory=AgentReplyMetaResponse)


class PlanRunStartedResponse(BaseModel):
    run_id: str
    session_id: str
    status: str = "queued"


class RunStatusResponse(BaseModel):
    run_id: str
    session_id: str
    status: str
    error_code: Optional[str] = None
    result: Optional[PlanResponse] = None


class SessionResponse(BaseModel):
    session_id: str
    title: str = ""
    turn_count: int
    mode: str
    current_route: Optional[dict]
    dialog_summary: str = ""
    assumptions: list[dict]
    route_intent: Optional[dict] = None
    recent_turns: list[dict] = Field(default_factory=list)
    turns: list[dict] = Field(default_factory=list)
    latest_response: Optional[dict] = None


class SessionListItemResponse(BaseModel):
    session_id: str
    title: str = ""
    dialog_summary: str = ""
    turn_count: int = 0
    route_count: int = 0
    updated_at: str | None = None


class SessionListResponse(BaseModel):
    sessions: list[SessionListItemResponse] = Field(default_factory=list)


class SessionUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=80)


class FeedbackRequest(BaseModel):
    session_id: str
    action: str  # "confirm" | "reject_poi" | "rate" | "overturn_assumption"
    poi_id: Optional[str] = None
    route_id: Optional[str] = None
    score: Optional[int] = None
    comment: Optional[str] = None
    overturned_assumption: Optional[str] = None
