"""API DTO。"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=128)
    display_name: str = Field(default="", max_length=80)
    tenant_name: str = Field(default="", max_length=80)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)
    tenant_id: Optional[str] = Field(default=None, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class AuthUserResponse(BaseModel):
    user_id: str
    email: str
    display_name: str


class AuthTenantResponse(BaseModel):
    tenant_id: str
    name: str
    role: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: AuthUserResponse
    tenant: AuthTenantResponse


class WorkspaceListResponse(BaseModel):
    workspaces: list[AuthTenantResponse] = Field(default_factory=list)


class SwitchWorkspaceRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class TenantMemberResponse(BaseModel):
    user_id: str
    email: str
    display_name: str
    role: Literal["owner", "member"]


class TenantMemberAddRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    role: Literal["owner", "member"] = "member"


class TenantMemberRoleRequest(BaseModel):
    role: Literal["owner", "member"]


class TenantMemberListResponse(BaseModel):
    members: list[TenantMemberResponse] = Field(default_factory=list)


class AuditEventResponse(BaseModel):
    event_id: int
    tenant_id: str
    actor_user_id: Optional[str] = None
    action: str
    target_type: str
    target_id: Optional[str] = None
    data: dict = Field(default_factory=dict)
    created_at: str


class AuditEventListResponse(BaseModel):
    events: list[AuditEventResponse] = Field(default_factory=list)


class AuthSessionResponse(BaseModel):
    session_id: str
    tenant_id: str
    created_at: str
    expires_at: str
    revoked_at: Optional[str] = None
    current: bool = False


class AuthSessionListResponse(BaseModel):
    sessions: list[AuthSessionResponse] = Field(default_factory=list)


class PlanRequest(BaseModel):
    query: str = Field(min_length=1)
    tenant_id: str = Field(default="default", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    user_id: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    session_id: Optional[str] = None
    idempotency_key: Optional[str] = Field(default=None, min_length=1, max_length=128)


class AgentReplyMetaResponse(BaseModel):
    plan_path: Optional[str] = None
    assumptions: list[dict] = Field(default_factory=list)
    relaxed_constraints: list[str] = Field(default_factory=list)
    degraded: bool = False
    next_suggested_user_moves: list[str] = Field(default_factory=list)
    phase_log: list[dict] = Field(default_factory=list)
    llm_calls: list[dict] = Field(default_factory=list)
    tool_calls: list[dict] = Field(default_factory=list)
    data_sources: list[str] = Field(default_factory=list)
    degraded_reasons: list[str] = Field(default_factory=list)
    token_usage: dict = Field(default_factory=dict)
    debug_trace_id: Optional[str] = None
    planning_decision: Optional[dict] = None
    turn_plan: Optional[dict] = None
    turn_context_meta: Optional[dict] = None
    pending_change: Optional[dict] = None
    rejected_change: Optional[dict] = None
    compiled_constraints: Optional[dict] = None
    active_policies: list[dict] = Field(default_factory=list)
    dropped_policies: list[dict] = Field(default_factory=list)
    blueprint_feasibility: list[dict] = Field(default_factory=list)
    planning_failures: list[dict] = Field(default_factory=list)
    repair_actions: list[dict] = Field(default_factory=list)


class PlanResponse(BaseModel):
    run_id: str
    turn_id: Optional[str] = None
    run_status: str
    plan_path: Optional[str]
    assumptions: list[dict]
    route_results: list[dict]
    presentation: Optional[dict]
    current_phase: str
    session_id: Optional[str] = None
    reply_type: str = "route"
    planning_outcome: str = "pending"
    diff_result: Optional[dict] = None
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


class RunCheckpointResponse(BaseModel):
    phase: str
    phase_index: int
    state: dict = Field(default_factory=dict)
    created_at: datetime


class RunCheckpointListResponse(BaseModel):
    run_id: str
    checkpoints: list[RunCheckpointResponse] = Field(default_factory=list)


class DeadLetterRunResponse(BaseModel):
    message_id: str
    source_message_id: str
    attempt: int
    error: str
    run_id: Optional[str] = None
    session_id: Optional[str] = None


class DeadLetterRunListResponse(BaseModel):
    entries: list[DeadLetterRunResponse] = Field(default_factory=list)


class SessionResponse(BaseModel):
    session_id: str
    tenant_id: str = "default"
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
    pending_change: Optional[dict] = None
    rejected_change: Optional[dict] = None


class SessionListItemResponse(BaseModel):
    session_id: str
    tenant_id: str = "default"
    title: str = ""
    dialog_summary: str = ""
    turn_count: int = 0
    route_count: int = 0
    updated_at: datetime | None = None


class SessionListResponse(BaseModel):
    sessions: list[SessionListItemResponse] = Field(default_factory=list)


class SessionUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    tenant_id: str = Field(default="default", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class FeedbackRequest(BaseModel):
    session_id: str
    tenant_id: str = Field(default="default", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    action: str  # "confirm" | "reject_poi" | "rate" | "overturn_assumption"
    poi_id: Optional[str] = None
    route_id: Optional[str] = None
    score: Optional[int] = None
    comment: Optional[str] = None
    overturned_assumption: Optional[str] = None
