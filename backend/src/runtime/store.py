"""Postgres-backed runtime state with an in-memory test fallback."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from ..models.profile import UserProfile
from ..models.session import SessionState, Turn


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


class RuntimeStore(Protocol):
    persistent: bool

    async def initialize(self) -> None: ...
    async def health(self) -> bool: ...
    async def load_session(self, session_id: str) -> SessionState | None: ...
    async def save_session(self, session: SessionState) -> None: ...
    async def list_sessions(self, user_id: str | None, limit: int) -> list[dict[str, Any]]: ...
    async def load_turns(self, session_id: str) -> list[Turn]: ...
    async def load_profile(self, user_id: str) -> UserProfile | None: ...
    async def save_profile(self, profile: UserProfile) -> None: ...
    async def create_run(self, run_id: str, session_id: str, request: dict[str, Any]) -> list[str]: ...
    async def set_run_status(
        self,
        run_id: str,
        status: str,
        *,
        result: dict[str, Any] | None = None,
        token_usage: dict[str, Any] | None = None,
        error_code: str | None = None,
    ) -> None: ...
    async def get_run(self, run_id: str) -> dict[str, Any] | None: ...
    async def append_event(self, run_id: str, event: dict[str, Any]) -> dict[str, Any]: ...
    async def get_events_after(self, run_id: str, event_id: int) -> list[dict[str, Any]]: ...
    async def mark_interrupted_runs(self) -> int: ...


class MemoryRuntimeStore:
    """Used only by isolated tests or when persistence is intentionally disabled."""

    persistent = False

    def __init__(self) -> None:
        self.sessions: dict[str, SessionState] = {}
        self.turns: dict[str, dict[str, Turn]] = {}
        self.profiles: dict[str, UserProfile] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.events: dict[str, list[dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        return None

    async def health(self) -> bool:
        return True

    async def load_session(self, session_id: str) -> SessionState | None:
        return self.sessions.get(session_id)

    async def save_session(self, session: SessionState) -> None:
        self.sessions[session.session_id] = session.model_copy(deep=True)
        stored = self.turns.setdefault(session.session_id, {})
        for turn in session.recent_turns:
            stored.setdefault(turn.turn_id, turn.model_copy(deep=True))

    async def list_sessions(self, user_id: str | None, limit: int) -> list[dict[str, Any]]:
        rows = []
        for session in self.sessions.values():
            if user_id and session.user_id != user_id:
                continue
            rows.append({
                "session_id": session.session_id,
                "title": session.title,
                "dialog_summary": session.dialog_summary,
                "turn_count": session.turn_count,
                "updated_at": session.recent_turns[-1].ts if session.recent_turns else "",
                "route_count": len(session.latest_response.get("route_results", [])) if session.latest_response else 0,
            })
        return sorted(rows, key=lambda row: row["updated_at"], reverse=True)[:limit]

    async def load_turns(self, session_id: str) -> list[Turn]:
        turns = self.turns.get(session_id, {})
        return sorted((turn.model_copy(deep=True) for turn in turns.values()), key=lambda turn: turn.ts)

    async def load_profile(self, user_id: str) -> UserProfile | None:
        profile = self.profiles.get(user_id)
        return profile.model_copy(deep=True) if profile else None

    async def save_profile(self, profile: UserProfile) -> None:
        self.profiles[profile.user_id] = profile.model_copy(deep=True)

    async def create_run(self, run_id: str, session_id: str, request: dict[str, Any]) -> list[str]:
        async with self._lock:
            cancelled = []
            for old_run in self.runs.values():
                if old_run["session_id"] == session_id and old_run["status"] in {"queued", "running"}:
                    old_run["status"] = "cancelled"
                    old_run["error_code"] = "superseded"
                    old_run["completed_at"] = _utc_now()
                    cancelled.append(old_run["run_id"])
            self.runs[run_id] = {
                "run_id": run_id,
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

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        run = self.runs.get(run_id)
        return dict(run) if run else None

    async def append_event(self, run_id: str, event: dict[str, Any]) -> dict[str, Any]:
        items = self.events.setdefault(run_id, [])
        stored = {"event_id": len(items) + 1, "run_id": run_id, "ts": _utc_now(), **event}
        items.append(stored)
        return stored

    async def get_events_after(self, run_id: str, event_id: int) -> list[dict[str, Any]]:
        return [event for event in self.events.get(run_id, []) if int(event["event_id"]) > event_id]

    async def mark_interrupted_runs(self) -> int:
        count = 0
        for run in self.runs.values():
            if run["status"] == "running":
                run["status"] = "failed"
                run["error_code"] = "worker_interrupted"
                run["completed_at"] = _utc_now()
                count += 1
        return count


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

    async def load_session(self, session_id: str) -> SessionState | None:
        await self.initialize()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT payload, version FROM sessions WHERE session_id = $1", session_id)
        if not row:
            return None
        payload = dict(row["payload"])
        payload["version"] = row["version"]
        return SessionState.model_validate(payload)

    async def save_session(self, session: SessionState) -> None:
        await self.initialize()
        payload = session.model_dump(mode="json", exclude={"version"})
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    INSERT INTO sessions (session_id, version, payload)
                    VALUES ($1, 1, $2::jsonb)
                    ON CONFLICT (session_id) DO UPDATE
                    SET version = sessions.version + 1, payload = EXCLUDED.payload, updated_at = NOW()
                    RETURNING version
                    """,
                    session.session_id,
                    _json(payload),
                )
                session.version = int(row["version"])
                for turn in session.recent_turns:
                    await conn.execute(
                        """
                        INSERT INTO turns (turn_id, session_id, payload)
                        VALUES ($1::uuid, $2, $3::jsonb)
                        ON CONFLICT (turn_id) DO NOTHING
                        """,
                        turn.turn_id,
                        session.session_id,
                        _json(turn.model_dump(mode="json")),
                    )

    async def list_sessions(self, user_id: str | None, limit: int) -> list[dict[str, Any]]:
        await self.initialize()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT session_id, payload->>'title' AS title,
                       payload->>'dialog_summary' AS dialog_summary,
                       COALESCE((payload->>'turn_count')::int, 0) AS turn_count,
                       COALESCE(jsonb_array_length(payload->'latest_response'->'route_results'), 0) AS route_count,
                       updated_at
                FROM sessions
                WHERE ($1::text IS NULL OR payload->>'user_id' = $1)
                ORDER BY updated_at DESC
                LIMIT $2
                """,
                user_id,
                limit,
            )
        return [dict(row) for row in rows]

    async def load_turns(self, session_id: str) -> list[Turn]:
        await self.initialize()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT payload FROM turns WHERE session_id = $1 ORDER BY created_at, turn_id",
                session_id,
            )
        return [Turn.model_validate(dict(row["payload"])) for row in rows]

    async def load_profile(self, user_id: str) -> UserProfile | None:
        await self.initialize()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT payload FROM user_profiles WHERE user_id = $1", user_id)
        return UserProfile.model_validate(dict(row["payload"])) if row else None

    async def save_profile(self, profile: UserProfile) -> None:
        await self.initialize()
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO user_profiles (user_id, payload) VALUES ($1, $2::jsonb)
                ON CONFLICT (user_id) DO UPDATE SET payload = EXCLUDED.payload, updated_at = NOW()
                """,
                profile.user_id,
                _json(profile.model_dump(mode="json")),
            )

    async def create_run(self, run_id: str, session_id: str, request: dict[str, Any]) -> list[str]:
        await self.initialize()
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", session_id)
                await conn.execute(
                    """
                    INSERT INTO sessions (session_id, version, payload)
                    VALUES ($1, 0, $2::jsonb)
                    ON CONFLICT (session_id) DO NOTHING
                    """,
                    session_id,
                    _json(SessionState(session_id=session_id).model_dump(mode="json", exclude={"version"})),
                )
                rows = await conn.fetch(
                    """
                    UPDATE runs SET status = 'cancelled', error_code = 'superseded', completed_at = NOW()
                    WHERE session_id = $1 AND status IN ('queued', 'running')
                    RETURNING run_id::text
                    """,
                    session_id,
                )
                await conn.execute(
                    "INSERT INTO runs (run_id, session_id, status, request) VALUES ($1::uuid, $2, 'queued', $3::jsonb)",
                    run_id,
                    session_id,
                    _json(request),
                )
        return [row["run_id"] for row in rows]

    async def set_run_status(self, run_id: str, status: str, **updates: Any) -> None:
        await self.initialize()
        result = _json(updates["result"]) if updates.get("result") is not None else None
        usage = _json(updates["token_usage"]) if updates.get("token_usage") is not None else None
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

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        await self.initialize()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM runs WHERE run_id = $1::uuid", run_id)
        return dict(row) if row else None

    async def append_event(self, run_id: str, event: dict[str, Any]) -> dict[str, Any]:
        await self.initialize()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO run_events (run_id, phase, status, summary, data)
                VALUES ($1::uuid, $2, $3, $4, $5::jsonb)
                RETURNING event_id, run_id::text, phase, status, ts, summary, data
                """,
                run_id,
                event.get("phase", "runtime"),
                event.get("status", "completed"),
                event.get("summary"),
                _json(event.get("data") or {}),
            )
        return dict(row)

    async def get_events_after(self, run_id: str, event_id: int) -> list[dict[str, Any]]:
        await self.initialize()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT event_id, run_id::text, phase, status, ts, summary, data FROM run_events WHERE run_id = $1::uuid AND event_id > $2 ORDER BY event_id",
                run_id,
                event_id,
            )
        return [dict(row) for row in rows]

    async def mark_interrupted_runs(self) -> int:
        await self.initialize()
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE runs SET status = 'failed', error_code = 'worker_interrupted', completed_at = NOW() WHERE status = 'running'"
            )
        return int(result.split()[-1])


def build_runtime_store(database_url: str) -> RuntimeStore:
    return PostgresRuntimeStore(database_url) if database_url else MemoryRuntimeStore()
