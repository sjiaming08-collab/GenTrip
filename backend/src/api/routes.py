"""HTTP routes for synchronous and asynchronous route planning."""

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import PlainTextResponse

from ..config import settings
from ..observability.metrics import runtime_metrics
from ..runtime.task_queue import QueueUnavailable
from .container import plan_service
from .presentation import response_from_state
from .tenant_auth import RequestIdentity, resolve_identity
from ..services.auth_service import AuthService
from ..services.auth_rate_limit import LoginRateLimiter
from .schemas import (
    FeedbackRequest,
    AuthResponse,
    AuthSessionListResponse,
    AuthSessionResponse,
    AuditEventListResponse,
    AuditEventResponse,
    AuthTenantResponse,
    AuthUserResponse,
    LoginRequest,
    PlanRequest,
    PlanResponse,
    PlanRunStartedResponse,
    RunStatusResponse,
    SessionListResponse,
    SessionResponse,
    SessionUpdateRequest,
    RegisterRequest,
    SwitchWorkspaceRequest,
    TenantMemberAddRequest,
    TenantMemberListResponse,
    TenantMemberResponse,
    TenantMemberRoleRequest,
    WorkspaceListResponse,
)

router = APIRouter()
login_rate_limiter = LoginRateLimiter()


def _auth_service() -> AuthService:
    return AuthService(plan_service._store)


async def _request_identity(request: Request, requested_tenant: str | None = None) -> RequestIdentity:
    identity = resolve_identity(request, requested_tenant)
    if identity.user_id:
        if identity.session_id:
            await _auth_service().validate_access_session(identity.session_id, identity.user_id, identity.tenant_id)
        # JWT claims set the scope, while this lookup makes membership removal and
        # user deactivation effective immediately rather than at token expiry.
        verified = await _auth_service().load_identity(identity.user_id, identity.tenant_id)
        return RequestIdentity(
            tenant_id=verified.membership.tenant_id,
            user_id=verified.user.user_id,
            role=verified.membership.role,
            session_id=identity.session_id,
            method=identity.method,
        )
    return identity


def _auth_response(identity, token: str) -> AuthResponse:
    return AuthResponse(
        access_token=token,
        user=AuthUserResponse(
            user_id=identity.user.user_id,
            email=identity.user.email,
            display_name=identity.user.display_name,
        ),
        tenant=AuthTenantResponse(
            tenant_id=identity.membership.tenant_id,
            name=identity.membership.tenant_name,
            role=identity.membership.role,
        ),
    )


def _set_access_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        "gentrip_access_token",
        token,
        max_age=settings.auth_access_token_minutes * 60,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )


async def _owned_session(session_id: str, identity: RequestIdentity):
    session = await plan_service.load_session(session_id, tenant_id=identity.tenant_id)
    if session is None or (identity.user_id and session.user_id and session.user_id != identity.user_id):
        raise HTTPException(status_code=404, detail="session_not_found")
    return session


async def _owned_run(run: dict, identity: RequestIdentity) -> None:
    if not identity.user_id:
        return
    requested_user = (run.get("request") or {}).get("user_id")
    if requested_user and requested_user != identity.user_id:
        raise HTTPException(status_code=404, detail="run_not_found")
    session = await plan_service.load_session(run["session_id"], tenant_id=identity.tenant_id)
    if session and session.user_id and session.user_id != identity.user_id:
        raise HTTPException(status_code=404, detail="run_not_found")


def _require_owner(identity: RequestIdentity) -> None:
    if identity.role != "owner":
        raise HTTPException(status_code=403, detail="owner_role_required")


async def _audit(identity: RequestIdentity, action: str, target_type: str, target_id: str | None = None, data: dict | None = None) -> None:
    await plan_service._store.append_audit_event(identity.tenant_id, identity.user_id, action, target_type, target_id, data)


@router.post("/auth/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(request: RegisterRequest, response: Response):
    identity = await _auth_service().register(request.email, request.password, request.display_name, request.tenant_name)
    token = await _auth_service().issue_access_token(identity)
    _set_access_cookie(response, token)
    await plan_service._store.append_audit_event(
        identity.membership.tenant_id,
        identity.user.user_id,
        "auth.register",
        "user",
        identity.user.user_id,
        {"email": identity.user.email},
    )
    return _auth_response(identity, token)


@router.post("/auth/login", response_model=AuthResponse)
async def login(credentials: LoginRequest, http_request: Request, response: Response):
    client_ip = http_request.client.host if http_request.client else "unknown"
    await login_rate_limiter.check(credentials.email, client_ip)
    try:
        identity = await _auth_service().authenticate(credentials.email, credentials.password, credentials.tenant_id)
    except HTTPException as exc:
        if exc.status_code == 401:
            await login_rate_limiter.record_failure(credentials.email, client_ip)
        raise
    await login_rate_limiter.reset(credentials.email, client_ip)
    token = await _auth_service().issue_access_token(identity)
    _set_access_cookie(response, token)
    await plan_service._store.append_audit_event(
        identity.membership.tenant_id,
        identity.user.user_id,
        "auth.login",
        "user",
        identity.user.user_id,
        {"method": "password"},
    )
    return _auth_response(identity, token)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response):
    try:
        claims = resolve_identity(request)
    except HTTPException:
        claims = None
    if claims and claims.user_id and claims.session_id:
        revoked = await plan_service._store.revoke_auth_session(claims.session_id, claims.user_id, "logout")
        if revoked:
            await plan_service._store.append_audit_event(
                claims.tenant_id, claims.user_id, "auth.logout", "auth_session", claims.session_id
            )
    response.delete_cookie("gentrip_access_token", path="/")


@router.get("/auth/me", response_model=AuthResponse)
async def me(request: Request):
    claims = await _request_identity(request)
    if not claims.user_id:
        raise HTTPException(status_code=401, detail="human_authentication_required")
    identity = await _auth_service().load_identity(claims.user_id, claims.tenant_id)
    # This endpoint intentionally does not mint a new token.
    return _auth_response(identity, "")


@router.get("/auth/workspaces", response_model=WorkspaceListResponse)
async def workspaces(request: Request):
    claims = await _request_identity(request)
    if not claims.user_id:
        raise HTTPException(status_code=401, detail="human_authentication_required")
    memberships = await _auth_service().list_workspaces(claims.user_id)
    return WorkspaceListResponse(
        workspaces=[
            AuthTenantResponse(tenant_id=item.tenant_id, name=item.tenant_name, role=item.role)
            for item in memberships
        ]
    )


@router.post("/auth/switch-workspace", response_model=AuthResponse)
async def switch_workspace(request: Request, body: SwitchWorkspaceRequest, response: Response):
    claims = await _request_identity(request)
    if not claims.user_id:
        raise HTTPException(status_code=401, detail="human_authentication_required")
    identity = await _auth_service().load_identity(claims.user_id, body.tenant_id)
    token = await _auth_service().issue_access_token(identity)
    _set_access_cookie(response, token)
    await plan_service._store.append_audit_event(
        identity.membership.tenant_id,
        identity.user.user_id,
        "auth.switch_workspace",
        "tenant",
        identity.membership.tenant_id,
    )
    return _auth_response(identity, token)


@router.get("/auth/sessions", response_model=AuthSessionListResponse)
async def auth_sessions(request: Request, limit: int = 20):
    claims = await _request_identity(request)
    if not claims.user_id:
        raise HTTPException(status_code=401, detail="human_authentication_required")
    rows = await plan_service._store.list_auth_sessions(claims.user_id, min(max(limit, 1), 100))
    return AuthSessionListResponse(sessions=[AuthSessionResponse(
        session_id=row["session_id"], tenant_id=row["tenant_id"],
        created_at=str(row["created_at"]), expires_at=str(row["expires_at"]),
        revoked_at=str(row["revoked_at"]) if row.get("revoked_at") else None,
        current=row["session_id"] == claims.session_id,
    ) for row in rows])


@router.delete("/auth/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_auth_session(request: Request, session_id: str):
    claims = await _request_identity(request)
    if not claims.user_id:
        raise HTTPException(status_code=401, detail="human_authentication_required")
    if not await plan_service._store.revoke_auth_session(session_id, claims.user_id, "user_revoked"):
        raise HTTPException(status_code=404, detail="auth_session_not_found")
    await _audit(claims, "auth.session_revoked", "auth_session", session_id)


@router.post("/auth/sessions/revoke-others", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_other_auth_sessions(request: Request):
    claims = await _request_identity(request)
    if not claims.user_id or not claims.session_id:
        raise HTTPException(status_code=401, detail="human_authentication_required")
    count = await plan_service._store.revoke_other_auth_sessions(claims.user_id, claims.session_id)
    await _audit(claims, "auth.other_sessions_revoked", "auth_session", data={"count": count})


@router.get("/tenants/current/members", response_model=TenantMemberListResponse)
async def list_tenant_members(request: Request):
    identity = await _request_identity(request)
    _require_owner(identity)
    members = await _auth_service().list_members(identity.tenant_id)
    return TenantMemberListResponse(members=[TenantMemberResponse(**member.model_dump()) for member in members])


@router.post("/tenants/current/members", response_model=TenantMemberResponse, status_code=status.HTTP_201_CREATED)
async def add_tenant_member(request: Request, body: TenantMemberAddRequest):
    identity = await _request_identity(request)
    _require_owner(identity)
    member = await _auth_service().add_member(identity.tenant_id, body.email, body.role)
    await _audit(identity, "tenant.member_added", "user", member.user_id, {"role": member.role})
    return TenantMemberResponse(**member.model_dump())


@router.patch("/tenants/current/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def update_tenant_member(request: Request, user_id: str, body: TenantMemberRoleRequest):
    identity = await _request_identity(request)
    _require_owner(identity)
    await _auth_service().update_member_role(identity.tenant_id, user_id, body.role)
    await _audit(identity, "tenant.member_role_updated", "user", user_id, {"role": body.role})


@router.delete("/tenants/current/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant_member(request: Request, user_id: str):
    identity = await _request_identity(request)
    _require_owner(identity)
    await _auth_service().remove_member(identity.tenant_id, user_id)
    await _audit(identity, "tenant.member_removed", "user", user_id)


@router.get("/tenants/current/audit-events", response_model=AuditEventListResponse)
async def list_tenant_audit_events(request: Request, limit: int = 50):
    identity = await _request_identity(request)
    _require_owner(identity)
    events = await plan_service._store.list_audit_events(identity.tenant_id, min(max(limit, 1), 200))
    return AuditEventListResponse(
        events=[AuditEventResponse(**{**event, "created_at": str(event["created_at"])}) for event in events]
    )


@router.get("/metrics", include_in_schema=False)
async def metrics():
    return PlainTextResponse(
        runtime_metrics.render_prometheus(await plan_service._store.aggregate_run_metrics()),
        media_type="text/plain; version=0.0.4",
    )


@router.get("/health")
async def health():
    dependencies = await plan_service.health()
    required_dependencies = [dependencies["database"]]
    if settings.redis_url:
        required_dependencies.append(dependencies["redis"])
    return {
        "status": "ok" if all(required_dependencies) else "degraded",
        "app": settings.app_name,
        "step": "A-cold-path",
        "runtime_stage": "P2-turn-orchestrator",
        "runtime_mode": "persistent" if plan_service.persistent else "in_memory_test",
        "dependencies": dependencies,
        "auth_enabled": settings.auth_enabled,
        "llm_enabled": settings.llm_enabled,
        "llm_model": settings.llm_model if settings.llm_enabled else None,
    }


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(request: Request, session_id: str, tenant_id: str = "default"):
    identity = await _request_identity(request, tenant_id)
    session = await _owned_session(session_id, identity)
    turns = await plan_service.load_turns(session_id, tenant_id=identity.tenant_id)
    return SessionResponse(
        session_id=session.session_id,
        tenant_id=session.tenant_id,
        title=session.title,
        turn_count=session.turn_count,
        mode=session.mode,
        current_route=session.current_route,
        dialog_summary=session.dialog_summary,
        assumptions=session.assumptions,
        route_intent=session.route_intent.model_dump(mode="json") if session.route_intent else None,
        recent_turns=[turn.model_dump(mode="json") for turn in session.recent_turns],
        turns=[turn.model_dump(mode="json") for turn in turns],
        latest_response=session.latest_response,
        pending_change=session.pending_change,
        rejected_change=session.rejected_change,
    )


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(request: Request, user_id: str | None = None, tenant_id: str = "default", limit: int = 30):
    identity = await _request_identity(request, tenant_id)
    rows = await plan_service.list_sessions(identity.user_id or user_id, limit=min(max(limit, 1), 100), tenant_id=identity.tenant_id)
    return SessionListResponse(sessions=rows)


@router.patch("/sessions/{session_id}", response_model=SessionResponse)
async def update_session(http_request: Request, session_id: str, request: SessionUpdateRequest):
    identity = await _request_identity(http_request, request.tenant_id)
    await _owned_session(session_id, identity)
    session = await plan_service.rename_session(session_id, request.title, tenant_id=identity.tenant_id)
    turns = await plan_service.load_turns(session_id, tenant_id=identity.tenant_id)
    return SessionResponse(
        session_id=session.session_id,
        tenant_id=session.tenant_id,
        title=session.title,
        turn_count=session.turn_count,
        mode=session.mode,
        current_route=session.current_route,
        dialog_summary=session.dialog_summary,
        assumptions=session.assumptions,
        route_intent=session.route_intent.model_dump(mode="json") if session.route_intent else None,
        recent_turns=[turn.model_dump(mode="json") for turn in session.recent_turns],
        turns=[turn.model_dump(mode="json") for turn in turns],
        latest_response=session.latest_response,
        pending_change=session.pending_change,
        rejected_change=session.rejected_change,
    )


@router.post("/routes/plan", response_model=PlanResponse)
async def plan_route(http_request: Request, request: PlanRequest):
    identity = await _request_identity(http_request, request.tenant_id)
    state = await plan_service.run_plan(
        request.query,
        tenant_id=identity.tenant_id,
        user_id=identity.user_id or request.user_id,
        user_lat=request.lat,
        user_lng=request.lng,
        session_id=request.session_id,
    )
    if state.get("run_status") == "failed":
        raise HTTPException(status_code=500, detail=state.get("error") or "plan_run_failed")
    if state.get("run_status") == "cancelled":
        raise HTTPException(status_code=409, detail="plan_run_cancelled")
    return response_from_state(state)


@router.post("/routes/plan/runs", response_model=PlanRunStartedResponse, status_code=202)
async def start_plan_run(http_request: Request, request: PlanRequest):
    identity = await _request_identity(http_request, request.tenant_id)
    try:
        started = await plan_service.start_plan(
            request.query,
            tenant_id=identity.tenant_id,
            user_id=identity.user_id or request.user_id,
            user_lat=request.lat,
            user_lng=request.lng,
            session_id=request.session_id,
            idempotency_key=request.idempotency_key,
        )
    except QueueUnavailable as exc:
        raise HTTPException(status_code=503, detail="plan_queue_unavailable") from exc
    return PlanRunStartedResponse(**started)


@router.get("/routes/plan/runs/{run_id}", response_model=RunStatusResponse)
async def get_plan_run(request: Request, run_id: str, tenant_id: str = "default"):
    identity = await _request_identity(request, tenant_id)
    run = await plan_service.get_run(run_id, tenant_id=identity.tenant_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run_not_found")
    await _owned_run(run, identity)
    result = run.get("result")
    return RunStatusResponse(
        run_id=run["run_id"],
        session_id=run["session_id"],
        status=run["status"],
        error_code=run.get("error_code"),
        result=response_from_state(result) if result and result.get("run_status") != "failed" else None,
    )


@router.post("/routes/plan/runs/{run_id}/cancel")
async def cancel_plan_run(request: Request, run_id: str, tenant_id: str = "default"):
    identity = await _request_identity(request, tenant_id)
    run = await plan_service.get_run(run_id, tenant_id=identity.tenant_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run_not_found")
    await _owned_run(run, identity)
    if not await plan_service.cancel_run(run_id, tenant_id=identity.tenant_id):
        raise HTTPException(status_code=409, detail="run_not_cancellable")
    return {"run_id": run_id, "status": "cancelled"}


@router.post("/routes/feedback")
async def submit_feedback(http_request: Request, request: FeedbackRequest):
    identity = await _request_identity(http_request, request.tenant_id)
    await _owned_session(request.session_id, identity)
    try:
        session = await plan_service.apply_feedback(
            request.session_id,
            tenant_id=identity.tenant_id,
            action=request.action,
            poi_id=request.poi_id,
            route_id=request.route_id,
            score=request.score,
            comment=request.comment,
            overturned_assumption=request.overturned_assumption,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="unsupported_feedback_action") from exc
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    return {"status": "ok", "session_id": request.session_id, "mode": session.mode}
