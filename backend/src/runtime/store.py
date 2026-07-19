"""Postgres-backed runtime state with an in-memory test fallback."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from ..models.profile import UserProfile
from ..models.auth import AuthUser, TenantMember, TenantMembership
from ..models.session import SessionState, Turn

DEFAULT_TENANT_ID = "default"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    """Serialize only for non-asyncpg callers; Postgres uses its JSONB codec."""
    return json.dumps(value, ensure_ascii=False, default=str)


def _json_object(value: Any) -> dict[str, Any]:
    """Read legacy double-encoded JSONB rows while new writes use native dicts."""
    if isinstance(value, str):
        decoded = json.loads(value)
        if isinstance(decoded, dict):
            return decoded
    return dict(value or {})


class RuntimeStore(Protocol):
    persistent: bool

    async def initialize(self) -> None: ...
    async def health(self) -> bool: ...
    async def load_session(self, tenant_id: str, session_id: str) -> SessionState | None: ...
    async def save_session(self, session: SessionState) -> None: ...
    async def list_sessions(self, tenant_id: str, user_id: str | None, limit: int) -> list[dict[str, Any]]: ...
    async def load_turns(self, tenant_id: str, session_id: str) -> list[Turn]: ...
    async def load_profile(self, tenant_id: str, user_id: str) -> UserProfile | None: ...
    async def save_profile(self, tenant_id: str, profile: UserProfile) -> None: ...
    async def create_auth_identity(self, user: AuthUser, membership: TenantMembership) -> None: ...
    async def load_auth_user_by_email(self, email: str) -> AuthUser | None: ...
    async def load_auth_user_by_id(self, user_id: str) -> AuthUser | None: ...
    async def load_auth_membership(self, user_id: str, tenant_id: str | None = None) -> TenantMembership | None: ...
    async def list_auth_memberships(self, user_id: str) -> list[TenantMembership]: ...
    async def list_tenant_members(self, tenant_id: str) -> list[TenantMember]: ...
    async def add_tenant_member(self, tenant_id: str, user_id: str, role: str) -> None: ...
    async def update_tenant_member_role(self, tenant_id: str, user_id: str, role: str) -> str: ...
    async def remove_tenant_member(self, tenant_id: str, user_id: str) -> str: ...
    async def append_audit_event(self, tenant_id: str, actor_user_id: str | None, action: str, target_type: str, target_id: str | None, data: dict[str, Any] | None = None) -> None: ...
    async def list_audit_events(self, tenant_id: str, limit: int) -> list[dict[str, Any]]: ...
    async def create_auth_session(self, session_id: str, user_id: str, tenant_id: str, expires_at: str) -> None: ...
    async def get_auth_session(self, session_id: str) -> dict[str, Any] | None: ...
    async def list_auth_sessions(self, user_id: str, limit: int) -> list[dict[str, Any]]: ...
    async def revoke_auth_session(self, session_id: str, user_id: str, reason: str) -> bool: ...
    async def revoke_other_auth_sessions(self, user_id: str, current_session_id: str) -> int: ...
    async def create_run(self, run_id: str, tenant_id: str, session_id: str, request: dict[str, Any]) -> list[str]: ...
    async def find_run_by_idempotency(self, tenant_id: str, session_id: str, idempotency_key: str) -> dict[str, Any] | None: ...
    async def release_run_idempotency(self, tenant_id: str, run_id: str) -> None: ...
    async def set_run_status(
        self,
        run_id: str,
        status: str,
        *,
        result: dict[str, Any] | None = None,
        token_usage: dict[str, Any] | None = None,
        error_code: str | None = None,
    ) -> None: ...
    async def get_run(self, tenant_id: str, run_id: str) -> dict[str, Any] | None: ...
    async def append_event(self, tenant_id: str, run_id: str, event: dict[str, Any]) -> dict[str, Any]: ...
    async def get_events_after(self, tenant_id: str, run_id: str, event_id: int) -> list[dict[str, Any]]: ...
    async def mark_interrupted_runs(self) -> int: ...
    async def aggregate_run_metrics(self) -> dict[str, Any]: ...


class MemoryRuntimeStore:
    """Used only by isolated tests or when persistence is intentionally disabled."""

    persistent = False

    def __init__(self) -> None:
        self.sessions: dict[tuple[str, str], SessionState] = {}
        self.turns: dict[tuple[str, str], dict[str, Turn]] = {}
        self.profiles: dict[tuple[str, str], UserProfile] = {}
        self.auth_users: dict[str, AuthUser] = {}
        self.auth_users_by_email: dict[str, str] = {}
        self.memberships: dict[tuple[str, str], TenantMembership] = {}
        self.tenant_names: dict[str, str] = {DEFAULT_TENANT_ID: "Default workspace"}
        self.audit_events: list[dict[str, Any]] = []
        self.auth_sessions: dict[str, dict[str, Any]] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.events: dict[str, list[dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        return None

    async def health(self) -> bool:
        return True

    async def load_session(self, tenant_id: str, session_id: str | None = None) -> SessionState | None:
        if session_id is None:
            session_id, tenant_id = tenant_id, DEFAULT_TENANT_ID
        session = self.sessions.get((tenant_id, session_id))
        if session is None and tenant_id == DEFAULT_TENANT_ID:
            # Compatibility with pre-tenant isolated tests that seed sessions
            # directly by session_id.
            session = self.sessions.get(session_id)  # type: ignore[arg-type]
        return session.model_copy(deep=True) if session else None

    async def save_session(self, session: SessionState) -> None:
        key = (session.tenant_id, session.session_id)
        self.sessions[key] = session.model_copy(deep=True)
        stored = self.turns.setdefault(key, {})
        for turn in session.recent_turns:
            stored.setdefault(turn.turn_id, turn.model_copy(deep=True))

    async def list_sessions(self, tenant_id: str, user_id: str | None, limit: int) -> list[dict[str, Any]]:
        rows = []
        for session in self.sessions.values():
            if session.tenant_id != tenant_id:
                continue
            if user_id and session.user_id != user_id:
                continue
            rows.append({
                "session_id": session.session_id,
                "tenant_id": session.tenant_id,
                "title": session.title,
                "dialog_summary": session.dialog_summary,
                "turn_count": session.turn_count,
                "updated_at": session.recent_turns[-1].ts if session.recent_turns else "",
                "route_count": len(session.latest_response.get("route_results", [])) if session.latest_response else 0,
            })
        return sorted(rows, key=lambda row: row["updated_at"], reverse=True)[:limit]

    async def load_turns(self, tenant_id: str, session_id: str | None = None) -> list[Turn]:
        if session_id is None:
            session_id, tenant_id = tenant_id, DEFAULT_TENANT_ID
        turns = self.turns.get((tenant_id, session_id), {})
        return sorted((turn.model_copy(deep=True) for turn in turns.values()), key=lambda turn: turn.ts)

    async def load_profile(self, tenant_id: str, user_id: str) -> UserProfile | None:
        profile = self.profiles.get((tenant_id, user_id))
        return profile.model_copy(deep=True) if profile else None

    async def save_profile(self, tenant_id: str, profile: UserProfile) -> None:
        self.profiles[(tenant_id, profile.user_id)] = profile.model_copy(deep=True)

    async def create_auth_identity(self, user: AuthUser, membership: TenantMembership) -> None:
        async with self._lock:
            if user.email in self.auth_users_by_email:
                raise ValueError("email_already_registered")
            self.auth_users[user.user_id] = user.model_copy(deep=True)
            self.auth_users_by_email[user.email] = user.user_id
            self.memberships[(membership.tenant_id, membership.user_id)] = membership.model_copy(deep=True)
            self.tenant_names[membership.tenant_id] = membership.tenant_name

    async def load_auth_user_by_email(self, email: str) -> AuthUser | None:
        user_id = self.auth_users_by_email.get(email.lower())
        user = self.auth_users.get(user_id) if user_id else None
        return user.model_copy(deep=True) if user else None

    async def load_auth_user_by_id(self, user_id: str) -> AuthUser | None:
        user = self.auth_users.get(user_id)
        return user.model_copy(deep=True) if user else None

    async def load_auth_membership(self, user_id: str, tenant_id: str | None = None) -> TenantMembership | None:
        if tenant_id:
            membership = self.memberships.get((tenant_id, user_id))
            return membership.model_copy(deep=True) if membership else None
        memberships = [item for item in self.memberships.values() if item.user_id == user_id]
        if not memberships:
            return None
        return sorted(memberships, key=lambda item: item.tenant_id)[0].model_copy(deep=True)

    async def list_auth_memberships(self, user_id: str) -> list[TenantMembership]:
        return sorted(
            (
                item.model_copy(update={"tenant_name": self.tenant_names.get(item.tenant_id, item.tenant_name)})
                for item in self.memberships.values()
                if item.user_id == user_id
            ),
            key=lambda item: item.tenant_id,
        )

    async def list_tenant_members(self, tenant_id: str) -> list[TenantMember]:
        rows = []
        for (member_tenant_id, user_id), membership in self.memberships.items():
            if member_tenant_id != tenant_id:
                continue
            user = self.auth_users.get(user_id)
            if user:
                rows.append(TenantMember(user_id=user.user_id, email=user.email, display_name=user.display_name, role=membership.role))
        return sorted(rows, key=lambda item: (item.role != "owner", item.email))

    async def add_tenant_member(self, tenant_id: str, user_id: str, role: str) -> None:
        async with self._lock:
            if (tenant_id, user_id) in self.memberships:
                raise ValueError("membership_already_exists")
            user = self.auth_users.get(user_id)
            if user is None or not user.is_active:
                raise ValueError("user_not_found")
            self.memberships[(tenant_id, user_id)] = TenantMembership(
                tenant_id=tenant_id,
                user_id=user_id,
                role=role,
                tenant_name=self.tenant_names.get(tenant_id, ""),
            )

    async def update_tenant_member_role(self, tenant_id: str, user_id: str, role: str) -> str:
        async with self._lock:
            membership = self.memberships.get((tenant_id, user_id))
            if membership is None:
                return "membership_not_found"
            owners = sum(1 for item in self.memberships.values() if item.tenant_id == tenant_id and item.role == "owner")
            if membership.role == "owner" and role != "owner" and owners <= 1:
                return "last_owner"
            membership.role = role
            return "updated"

    async def remove_tenant_member(self, tenant_id: str, user_id: str) -> str:
        async with self._lock:
            membership = self.memberships.get((tenant_id, user_id))
            if membership is None:
                return "membership_not_found"
            owners = sum(1 for item in self.memberships.values() if item.tenant_id == tenant_id and item.role == "owner")
            if membership.role == "owner" and owners <= 1:
                return "last_owner"
            del self.memberships[(tenant_id, user_id)]
            return "removed"

    async def append_audit_event(self, tenant_id: str, actor_user_id: str | None, action: str, target_type: str, target_id: str | None, data: dict[str, Any] | None = None) -> None:
        async with self._lock:
            self.audit_events.append({
                "event_id": len(self.audit_events) + 1,
                "tenant_id": tenant_id,
                "actor_user_id": actor_user_id,
                "action": action,
                "target_type": target_type,
                "target_id": target_id,
                "data": data or {},
                "created_at": _utc_now(),
            })

    async def list_audit_events(self, tenant_id: str, limit: int) -> list[dict[str, Any]]:
        return [dict(event) for event in reversed(self.audit_events) if event["tenant_id"] == tenant_id][:limit]

    async def create_auth_session(self, session_id: str, user_id: str, tenant_id: str, expires_at: str) -> None:
        async with self._lock:
            self.auth_sessions[session_id] = {
                "session_id": session_id, "user_id": user_id, "tenant_id": tenant_id,
                "created_at": _utc_now(), "expires_at": expires_at, "revoked_at": None,
                "revoked_reason": None,
            }

    async def get_auth_session(self, session_id: str) -> dict[str, Any] | None:
        session = self.auth_sessions.get(session_id)
        return dict(session) if session else None

    async def list_auth_sessions(self, user_id: str, limit: int) -> list[dict[str, Any]]:
        rows = [dict(item) for item in self.auth_sessions.values() if item["user_id"] == user_id]
        return sorted(rows, key=lambda item: item["created_at"], reverse=True)[:limit]

    async def revoke_auth_session(self, session_id: str, user_id: str, reason: str) -> bool:
        async with self._lock:
            session = self.auth_sessions.get(session_id)
            if session is None or session["user_id"] != user_id:
                return False
            if session["revoked_at"] is None:
                session["revoked_at"] = _utc_now()
                session["revoked_reason"] = reason
            return True

    async def revoke_other_auth_sessions(self, user_id: str, current_session_id: str) -> int:
        async with self._lock:
            revoked = 0
            for session_id, session in self.auth_sessions.items():
                if session_id != current_session_id and session["user_id"] == user_id and session["revoked_at"] is None:
                    session["revoked_at"] = _utc_now()
                    session["revoked_reason"] = "revoke_others"
                    revoked += 1
            return revoked

    async def create_run(
        self,
        run_id: str,
        tenant_id: str,
        session_id: str | dict[str, Any],
        request: dict[str, Any] | None = None,
    ) -> list[str]:
        if request is None:
            request = session_id if isinstance(session_id, dict) else {}
            session_id, tenant_id = tenant_id, DEFAULT_TENANT_ID
        assert isinstance(session_id, str)
        async with self._lock:
            cancelled = []
            for old_run in self.runs.values():
                if old_run["tenant_id"] == tenant_id and old_run["session_id"] == session_id and old_run["status"] in {"queued", "running"}:
                    old_run["status"] = "cancelled"
                    old_run["error_code"] = "superseded"
                    old_run["completed_at"] = _utc_now()
                    cancelled.append(old_run["run_id"])
            self.runs[run_id] = {
                "run_id": run_id,
                "tenant_id": tenant_id,
                "session_id": session_id,
                "status": "queued",
                "request": request,
                "result": None,
                "token_usage": {},
                "error_code": None,
                "created_at": _utc_now(),
                "started_at": None,
                "completed_at": None,
            }
            return cancelled

    async def find_run_by_idempotency(self, tenant_id: str, session_id: str, idempotency_key: str) -> dict[str, Any] | None:
        for run in self.runs.values():
            if run["tenant_id"] == tenant_id and run["session_id"] == session_id and run["request"].get("idempotency_key") == idempotency_key:
                return dict(run)
        return None

    async def release_run_idempotency(self, tenant_id: str, run_id: str) -> None:
        run = await self.get_run(tenant_id, run_id)
        if run is not None:
            run["request"]["idempotency_key"] = None
            self.runs[run_id]["request"]["idempotency_key"] = None

    async def set_run_status(self, run_id: str, status: str, **updates: Any) -> None:
        run = self.runs[run_id]
        run["status"] = status
        if status == "running" and not run["started_at"]:
            run["started_at"] = _utc_now()
        if status in {"completed", "failed", "cancelled", "degraded"}:
            run["completed_at"] = _utc_now()
        for key in ("result", "token_usage", "error_code"):
            if key in updates and updates[key] is not None:
                run[key] = updates[key]

    async def get_run(self, tenant_id: str, run_id: str | None = None) -> dict[str, Any] | None:
        if run_id is None:
            run_id, tenant_id = tenant_id, DEFAULT_TENANT_ID
        run = self.runs.get(run_id)
        return dict(run) if run and run["tenant_id"] == tenant_id else None

    async def append_event(self, tenant_id: str, run_id: str, event: dict[str, Any]) -> dict[str, Any]:
        if await self.get_run(tenant_id, run_id) is None:
            raise KeyError("run_not_found")
        items = self.events.setdefault(run_id, [])
        stored = {"event_id": len(items) + 1, "run_id": run_id, "ts": _utc_now(), **event}
        items.append(stored)
        return stored

    async def get_events_after(self, tenant_id: str, run_id: str, event_id: int) -> list[dict[str, Any]]:
        if await self.get_run(tenant_id, run_id) is None:
            return []
        return [event for event in self.events.get(run_id, []) if int(event["event_id"]) > event_id]

    async def mark_interrupted_runs(self) -> int:
        count = 0
        for run in self.runs.values():
            if run["status"] == "running":
                run["status"] = "interrupted"
                run["error_code"] = "worker_interrupted"
                run["completed_at"] = _utc_now()
                count += 1
        return count

    async def aggregate_run_metrics(self) -> dict[str, Any]:
        runs: dict[tuple[str, str], int] = {}
        duration_seconds: dict[str, float] = {}
        tokens = {"prompt": 0, "completion": 0, "total": 0}
        for run in self.runs.values():
            status = str(run["status"])
            result = run.get("result") or {}
            path = str(result.get("plan_path") or "none") if isinstance(result, dict) else "none"
            runs[(status, path)] = runs.get((status, path), 0) + 1
            if run.get("started_at") and run.get("completed_at"):
                started = datetime.fromisoformat(str(run["started_at"]).replace("Z", "+00:00"))
                completed = datetime.fromisoformat(str(run["completed_at"]).replace("Z", "+00:00"))
                duration_seconds[status] = duration_seconds.get(status, 0.0) + max(0.0, (completed - started).total_seconds())
            for key, metric in (("prompt_tokens", "prompt"), ("completion_tokens", "completion"), ("total_tokens", "total")):
                tokens[metric] += int((run.get("token_usage") or {}).get(key) or 0)
        return {"runs": runs, "duration_seconds": duration_seconds, "token_usage": tokens}


class PostgresRuntimeStore:
    persistent = True

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        self._pool: Any = None

    async def initialize(self) -> None:
        if self._pool is not None:
            return
        import asyncpg

        self._pool = await asyncpg.create_pool(
            self.database_url,
            min_size=1,
            max_size=8,
            init=self._initialize_connection,
        )
        migrations_dir = Path(__file__).resolve().parents[2] / "migrations"
        async with self._pool.acquire() as conn:
            for migration in sorted(migrations_dir.glob("*.sql")):
                await conn.execute(migration.read_text(encoding="utf-8"))

    @staticmethod
    async def _initialize_connection(connection: Any) -> None:
        await connection.set_type_codec(
            "jsonb",
            schema="pg_catalog",
            encoder=lambda value: json.dumps(value, ensure_ascii=False, default=str),
            decoder=json.loads,
        )

    async def health(self) -> bool:
        try:
            await self.initialize()
            async with self._pool.acquire() as conn:
                return bool(await conn.fetchval("SELECT 1"))
        except Exception:
            return False

    async def load_session(self, tenant_id: str, session_id: str) -> SessionState | None:
        await self.initialize()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT payload, version FROM sessions WHERE tenant_id = $1 AND session_id = $2",
                tenant_id,
                session_id,
            )
        if not row:
            return None
        payload = _json_object(row["payload"])
        payload["version"] = row["version"]
        payload["tenant_id"] = tenant_id
        return SessionState.model_validate(payload)

    async def save_session(self, session: SessionState) -> None:
        await self.initialize()
        payload = session.model_dump(mode="json", exclude={"version"})
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    INSERT INTO sessions (tenant_id, session_id, version, payload)
                    VALUES ($1, $2, 1, $3::jsonb)
                    ON CONFLICT (tenant_id, session_id) DO UPDATE
                    SET version = sessions.version + 1, payload = EXCLUDED.payload, updated_at = NOW()
                    RETURNING version
                    """,
                    session.tenant_id,
                    session.session_id,
                    payload,
                )
                session.version = int(row["version"])
                for turn in session.recent_turns:
                    await conn.execute(
                        """
                        INSERT INTO turns (turn_id, tenant_id, session_id, payload)
                        VALUES ($1::uuid, $2, $3, $4::jsonb)
                        ON CONFLICT (turn_id) DO NOTHING
                        """,
                        turn.turn_id,
                        session.tenant_id,
                        session.session_id,
                        turn.model_dump(mode="json"),
                    )

    async def list_sessions(self, tenant_id: str, user_id: str | None, limit: int) -> list[dict[str, Any]]:
        await self.initialize()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT session_id, tenant_id, payload->>'title' AS title,
                       payload->>'dialog_summary' AS dialog_summary,
                       COALESCE((payload->>'turn_count')::int, 0) AS turn_count,
                       COALESCE(jsonb_array_length(payload->'latest_response'->'route_results'), 0) AS route_count,
                       updated_at
                FROM sessions
                WHERE tenant_id = $1 AND ($2::text IS NULL OR payload->>'user_id' = $2)
                ORDER BY updated_at DESC
                LIMIT $3
                """,
                tenant_id,
                user_id,
                limit,
            )
        return [dict(row) for row in rows]

    async def load_turns(self, tenant_id: str, session_id: str) -> list[Turn]:
        await self.initialize()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT payload FROM turns WHERE tenant_id = $1 AND session_id = $2 ORDER BY created_at, turn_id",
                tenant_id,
                session_id,
            )
        return [Turn.model_validate(_json_object(row["payload"])) for row in rows]

    async def load_profile(self, tenant_id: str, user_id: str) -> UserProfile | None:
        await self.initialize()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT payload FROM user_profiles WHERE tenant_id = $1 AND user_id = $2",
                tenant_id,
                user_id,
            )
        return UserProfile.model_validate(_json_object(row["payload"])) if row else None

    async def save_profile(self, tenant_id: str, profile: UserProfile) -> None:
        await self.initialize()
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO user_profiles (tenant_id, user_id, payload) VALUES ($1, $2, $3::jsonb)
                ON CONFLICT (tenant_id, user_id) DO UPDATE SET payload = EXCLUDED.payload, updated_at = NOW()
                """,
                tenant_id,
                profile.user_id,
                profile.model_dump(mode="json"),
            )

    async def create_auth_identity(self, user: AuthUser, membership: TenantMembership) -> None:
        await self.initialize()
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO tenants (tenant_id, name) VALUES ($1, $2)",
                    membership.tenant_id,
                    membership.tenant_name,
                )
                await conn.execute(
                    """
                    INSERT INTO auth_users (user_id, email, display_name, password_hash, is_active)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    user.user_id,
                    user.email,
                    user.display_name,
                    user.password_hash,
                    user.is_active,
                )
                await conn.execute(
                    "INSERT INTO tenant_memberships (tenant_id, user_id, role) VALUES ($1, $2, $3)",
                    membership.tenant_id,
                    membership.user_id,
                    membership.role,
                )

    async def load_auth_user_by_email(self, email: str) -> AuthUser | None:
        await self.initialize()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT user_id, email, display_name, password_hash, is_active FROM auth_users WHERE email = $1",
                email.lower(),
            )
        return AuthUser.model_validate(dict(row)) if row else None

    async def load_auth_user_by_id(self, user_id: str) -> AuthUser | None:
        await self.initialize()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT user_id, email, display_name, password_hash, is_active FROM auth_users WHERE user_id = $1",
                user_id,
            )
        return AuthUser.model_validate(dict(row)) if row else None

    async def load_auth_membership(self, user_id: str, tenant_id: str | None = None) -> TenantMembership | None:
        await self.initialize()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT m.tenant_id, m.user_id, m.role, t.name AS tenant_name
                FROM tenant_memberships m JOIN tenants t USING (tenant_id)
                WHERE m.user_id = $1 AND ($2::text IS NULL OR m.tenant_id = $2) AND EXISTS (
                    SELECT 1 FROM auth_users u WHERE u.user_id = m.user_id AND u.is_active
                )
                ORDER BY m.created_at, m.tenant_id
                LIMIT 1
                """,
                user_id,
                tenant_id,
            )
        return TenantMembership.model_validate(dict(row)) if row else None

    async def list_auth_memberships(self, user_id: str) -> list[TenantMembership]:
        await self.initialize()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT m.tenant_id, m.user_id, m.role, t.name AS tenant_name
                FROM tenant_memberships m JOIN tenants t USING (tenant_id)
                WHERE m.user_id = $1
                ORDER BY t.name, m.tenant_id
                """,
                user_id,
            )
        return [TenantMembership.model_validate(dict(row)) for row in rows]

    async def list_tenant_members(self, tenant_id: str) -> list[TenantMember]:
        await self.initialize()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT u.user_id, u.email, u.display_name, m.role
                FROM tenant_memberships m JOIN auth_users u USING (user_id)
                WHERE m.tenant_id = $1 AND u.is_active
                ORDER BY CASE WHEN m.role = 'owner' THEN 0 ELSE 1 END, u.email
                """,
                tenant_id,
            )
        return [TenantMember.model_validate(dict(row)) for row in rows]

    async def add_tenant_member(self, tenant_id: str, user_id: str, role: str) -> None:
        await self.initialize()
        async with self._pool.acquire() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO tenant_memberships (tenant_id, user_id, role)
                    SELECT $1, user_id, $3 FROM auth_users WHERE user_id = $2 AND is_active
                    """,
                    tenant_id,
                    user_id,
                    role,
                )
            except Exception as exc:
                if getattr(exc, "sqlstate", None) == "23505":
                    raise ValueError("membership_already_exists") from exc
                raise
        membership = await self.load_auth_membership(user_id, tenant_id)
        if membership is None:
            raise ValueError("user_not_found")

    async def update_tenant_member_role(self, tenant_id: str, user_id: str, role: str) -> str:
        await self.initialize()
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"tenant-owners:{tenant_id}")
                current = await conn.fetchrow(
                    "SELECT role FROM tenant_memberships WHERE tenant_id = $1 AND user_id = $2 FOR UPDATE",
                    tenant_id,
                    user_id,
                )
                if current is None:
                    return "membership_not_found"
                owners = await conn.fetchval("SELECT count(*) FROM tenant_memberships WHERE tenant_id = $1 AND role = 'owner'", tenant_id)
                if current["role"] == "owner" and role != "owner" and owners <= 1:
                    return "last_owner"
                await conn.execute("UPDATE tenant_memberships SET role = $3 WHERE tenant_id = $1 AND user_id = $2", tenant_id, user_id, role)
                return "updated"

    async def remove_tenant_member(self, tenant_id: str, user_id: str) -> str:
        await self.initialize()
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"tenant-owners:{tenant_id}")
                current = await conn.fetchrow(
                    "SELECT role FROM tenant_memberships WHERE tenant_id = $1 AND user_id = $2 FOR UPDATE",
                    tenant_id,
                    user_id,
                )
                if current is None:
                    return "membership_not_found"
                owners = await conn.fetchval("SELECT count(*) FROM tenant_memberships WHERE tenant_id = $1 AND role = 'owner'", tenant_id)
                if current["role"] == "owner" and owners <= 1:
                    return "last_owner"
                await conn.execute("DELETE FROM tenant_memberships WHERE tenant_id = $1 AND user_id = $2", tenant_id, user_id)
                return "removed"

    async def append_audit_event(self, tenant_id: str, actor_user_id: str | None, action: str, target_type: str, target_id: str | None, data: dict[str, Any] | None = None) -> None:
        await self.initialize()
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO audit_events (tenant_id, actor_user_id, action, target_type, target_id, data)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                """,
                tenant_id,
                actor_user_id,
                action,
                target_type,
                target_id,
                data or {},
            )

    async def list_audit_events(self, tenant_id: str, limit: int) -> list[dict[str, Any]]:
        await self.initialize()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT event_id, tenant_id, actor_user_id, action, target_type, target_id, data, created_at
                FROM audit_events WHERE tenant_id = $1 ORDER BY event_id DESC LIMIT $2
                """,
                tenant_id,
                limit,
            )
        return [dict(row) for row in rows]

    async def create_auth_session(self, session_id: str, user_id: str, tenant_id: str, expires_at: str) -> None:
        await self.initialize()
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO auth_sessions (session_id, user_id, tenant_id, expires_at) VALUES ($1, $2, $3, $4::timestamptz)",
                session_id, user_id, tenant_id, expires_at,
            )

    async def get_auth_session(self, session_id: str) -> dict[str, Any] | None:
        await self.initialize()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM auth_sessions WHERE session_id = $1", session_id)
        if not row:
            return None
        result = dict(row)
        for key in ("request", "result", "token_usage"):
            if result.get(key) is not None:
                result[key] = _json_object(result[key])
        return result

    async def list_auth_sessions(self, user_id: str, limit: int) -> list[dict[str, Any]]:
        await self.initialize()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM auth_sessions WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2", user_id, limit
            )
        return [dict(row) for row in rows]

    async def revoke_auth_session(self, session_id: str, user_id: str, reason: str) -> bool:
        await self.initialize()
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE auth_sessions SET revoked_at = COALESCE(revoked_at, NOW()), revoked_reason = COALESCE(revoked_reason, $3) WHERE session_id = $1 AND user_id = $2",
                session_id, user_id, reason,
            )
        return result.endswith("1")

    async def revoke_other_auth_sessions(self, user_id: str, current_session_id: str) -> int:
        await self.initialize()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "UPDATE auth_sessions SET revoked_at = NOW(), revoked_reason = 'revoke_others' WHERE user_id = $1 AND session_id != $2 AND revoked_at IS NULL RETURNING session_id",
                user_id, current_session_id,
            )
        return len(rows)

    async def create_run(self, run_id: str, tenant_id: str, session_id: str, request: dict[str, Any]) -> list[str]:
        await self.initialize()
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"{tenant_id}:{session_id}")
                await conn.execute(
                    """
                    INSERT INTO sessions (tenant_id, session_id, version, payload)
                    VALUES ($1, $2, 0, $3::jsonb)
                    ON CONFLICT (tenant_id, session_id) DO NOTHING
                    """,
                    tenant_id,
                    session_id,
                    SessionState(session_id=session_id, tenant_id=tenant_id).model_dump(mode="json", exclude={"version"}),
                )
                rows = await conn.fetch(
                    """
                    UPDATE runs SET status = 'cancelled', error_code = 'superseded', completed_at = NOW()
                    WHERE tenant_id = $1 AND session_id = $2 AND status IN ('queued', 'running')
                    RETURNING run_id::text
                    """,
                    tenant_id,
                    session_id,
                )
                await conn.execute(
                    "INSERT INTO runs (run_id, tenant_id, session_id, status, request, idempotency_key) VALUES ($1::uuid, $2, $3, 'queued', $4::jsonb, $5)",
                    run_id,
                    tenant_id,
                    session_id,
                    request,
                    request.get("idempotency_key"),
                )
        return [row["run_id"] for row in rows]

    async def find_run_by_idempotency(self, tenant_id: str, session_id: str, idempotency_key: str) -> dict[str, Any] | None:
        await self.initialize()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM runs WHERE tenant_id = $1 AND session_id = $2 AND idempotency_key = $3",
                tenant_id,
                session_id,
                idempotency_key,
            )
        return dict(row) if row else None

    async def release_run_idempotency(self, tenant_id: str, run_id: str) -> None:
        await self.initialize()
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE runs SET idempotency_key = NULL WHERE tenant_id = $1 AND run_id = $2::uuid",
                tenant_id,
                run_id,
            )

    async def set_run_status(self, run_id: str, status: str, **updates: Any) -> None:
        await self.initialize()
        result = updates.get("result")
        usage = updates.get("token_usage")
        error_code = updates.get("error_code")
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE runs SET status = $2,
                    result = COALESCE($3::jsonb, result),
                    token_usage = COALESCE($4::jsonb, token_usage),
                    error_code = COALESCE($5, error_code),
                    started_at = CASE WHEN $2 = 'running' AND started_at IS NULL THEN NOW() ELSE started_at END,
                    completed_at = CASE WHEN $2 IN ('completed', 'failed', 'cancelled', 'degraded') THEN NOW() ELSE completed_at END
                WHERE run_id = $1::uuid
                """,
                run_id,
                status,
                result,
                usage,
                error_code,
            )

    async def get_run(self, tenant_id: str, run_id: str) -> dict[str, Any] | None:
        await self.initialize()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM runs WHERE tenant_id = $1 AND run_id = $2::uuid",
                tenant_id,
                run_id,
            )
        if not row:
            return None
        run = dict(row)
        run["run_id"] = str(run["run_id"])
        for key in ("request", "result", "token_usage"):
            if run.get(key) is not None:
                run[key] = _json_object(run[key])
        return run

    async def append_event(self, tenant_id: str, run_id: str, event: dict[str, Any]) -> dict[str, Any]:
        await self.initialize()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO run_events (run_id, phase, status, summary, data)
                SELECT run_id, $3, $4, $5, $6::jsonb
                FROM runs WHERE tenant_id = $1 AND run_id = $2::uuid
                RETURNING event_id, run_id::text, phase, status, ts, summary, data
                """,
                tenant_id,
                run_id,
                event.get("phase", "runtime"),
                event.get("status", "completed"),
                event.get("summary"),
                event.get("data") or {},
            )
        if row is None:
            raise KeyError("run_not_found")
        event_row = dict(row)
        event_row["run_id"] = str(event_row["run_id"])
        event_row["data"] = _json_object(event_row.get("data"))
        return event_row

    async def get_events_after(self, tenant_id: str, run_id: str, event_id: int) -> list[dict[str, Any]]:
        await self.initialize()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT run_events.event_id, run_events.run_id::text,
                       run_events.phase, run_events.status, run_events.ts,
                       run_events.summary, run_events.data
                FROM run_events JOIN runs USING (run_id)
                WHERE runs.tenant_id = $1 AND run_events.run_id = $2::uuid AND run_events.event_id > $3
                ORDER BY run_events.event_id
                """,
                tenant_id,
                run_id,
                event_id,
            )
        events = []
        for row in rows:
            event = dict(row)
            event["run_id"] = str(event["run_id"])
            event["data"] = _json_object(event.get("data"))
            events.append(event)
        return events

    async def mark_interrupted_runs(self) -> int:
        await self.initialize()
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE runs SET status = 'interrupted', error_code = 'worker_interrupted', completed_at = NOW() WHERE status = 'running'"
            )
        return int(result.split()[-1])

    async def aggregate_run_metrics(self) -> dict[str, Any]:
        await self.initialize()
        async with self._pool.acquire() as conn:
            run_rows = await conn.fetch(
                """
                SELECT status, COALESCE(NULLIF(result->>'plan_path', ''), 'none') AS path,
                       count(*) AS count,
                       COALESCE(sum(EXTRACT(EPOCH FROM (completed_at - started_at))), 0) AS duration_seconds
                FROM runs GROUP BY status, path
                """
            )
            token_row = await conn.fetchrow(
                """
                SELECT
                  COALESCE(sum(CASE WHEN jsonb_typeof(token_usage) = 'object' THEN COALESCE((token_usage->>'prompt_tokens')::bigint, 0) ELSE 0 END), 0) AS prompt,
                  COALESCE(sum(CASE WHEN jsonb_typeof(token_usage) = 'object' THEN COALESCE((token_usage->>'completion_tokens')::bigint, 0) ELSE 0 END), 0) AS completion,
                  COALESCE(sum(CASE WHEN jsonb_typeof(token_usage) = 'object' THEN COALESCE((token_usage->>'total_tokens')::bigint, 0) ELSE 0 END), 0) AS total
                FROM runs
                """
            )
        return {
            "runs": {(str(row["status"]), str(row["path"])): int(row["count"]) for row in run_rows},
            "duration_seconds": {str(row["status"]): float(row["duration_seconds"]) for row in run_rows},
            "token_usage": {key: int(token_row[key]) for key in ("prompt", "completion", "total")},
        }


def build_runtime_store(database_url: str) -> RuntimeStore:
    return PostgresRuntimeStore(database_url) if database_url else MemoryRuntimeStore()
