"""Plan orchestration, durable run lifecycle, and live phase events."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from uuid import uuid4

from ..config import settings
from ..graph.plan_graph import create_plan_agent
from ..graph.state import build_initial_state, llm_call_from_meta, token_usage_from_calls, utc_now_iso
from ..llm.session_summary import summarize_session_with_meta
from ..models.memory import MemoryContext
from ..models.profile import UserProfile
from ..models.reply import ReplyType
from ..models.session import RouteIntent, SessionState, Turn
from ..runtime.events import RuntimeEventBus
from ..runtime.store import RuntimeStore, build_runtime_store


logger = logging.getLogger(__name__)
_TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled", "degraded"}


class RunCancelled(Exception):
    """Raised between graph nodes after a user cancels or supersedes a run."""


def infer_reply_type(state: dict) -> str:
    if state.get("turn_mode") == "reject" or state.get("reply_type") == ReplyType.REJECT.value:
        return ReplyType.REJECT.value
    if state.get("reply_type") == ReplyType.DIFF.value:
        return ReplyType.DIFF.value
    if state.get("degraded"):
        return ReplyType.DEGRADED_ROUTE.value
    if len(state.get("route_results") or []) >= 2:
        return ReplyType.MULTI_ROUTE.value
    return ReplyType.ROUTE.value


def response_snapshot(state: dict) -> dict[str, Any]:
    """Persist the client-facing route payload without prompts or secrets."""
    llm_calls = state.get("llm_calls") or []
    reply_type = infer_reply_type(state)
    return {
        "run_id": state["run_id"],
        "session_id": state.get("session_id"),
        "run_status": state.get("run_status", "completed"),
        "plan_path": state.get("plan_path"),
        "assumptions": state.get("assumptions", []),
        "route_results": state.get("route_results", []),
        "structured": state.get("route_results", []),
        "presentation": state.get("presentation"),
        "current_phase": state.get("current_phase", "done"),
        "reply_type": reply_type,
        "meta": {
            "plan_path": state.get("plan_path"),
            "assumptions": state.get("assumptions", []),
            "relaxed_constraints": state.get("relaxed_constraints", []),
            "degraded": bool(state.get("degraded", False)),
            "next_suggested_user_moves": [],
            "phase_log": state.get("phase_log") or [],
            "llm_calls": llm_calls,
            "token_usage": token_usage_from_calls(llm_calls),
            "debug_trace_id": state.get("run_id"),
        },
    }


class PlanService:
    def __init__(self, store: RuntimeStore | None = None, event_bus: RuntimeEventBus | None = None) -> None:
        self._agent = create_plan_agent()
        self._store = store or build_runtime_store(settings.database_url)
        self._event_bus = event_bus or RuntimeEventBus(settings.redis_url)
        # Compatibility for existing isolated tests that seed the in-memory store directly.
        self._sessions = getattr(self._store, "sessions", {})
        self._profiles = getattr(self._store, "profiles", {})
        self._tasks: dict[str, asyncio.Task[dict]] = {}
        self._initialized = False
        self._initialize_lock = asyncio.Lock()

    @property
    def persistent(self) -> bool:
        return self._store.persistent

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._initialize_lock:
            if self._initialized:
                return
            await self._store.initialize()
            await self._event_bus.initialize()
            await self._store.mark_interrupted_runs()
            self._initialized = True

    async def health(self) -> dict[str, bool]:
        try:
            await self.initialize()
            database = await self._store.health()
        except Exception:
            database = False
        await self._event_bus.initialize()
        return {"database": database, "redis": self._event_bus.available}

    def get_session(self, session_id: str) -> SessionState | None:
        """Backward-compatible synchronous lookup for the in-memory test store."""
        if self.persistent:
            raise RuntimeError("use load_session() when the persistent runtime is enabled")
        return self._sessions.get(session_id)

    async def load_session(self, session_id: str) -> SessionState | None:
        await self.initialize()
        cached = await self._event_bus.get_session(session_id)
        if cached:
            try:
                return SessionState.model_validate(cached)
            except Exception:
                pass
        session = await self._store.load_session(session_id)
        if session:
            await self._cache_session(session)
        return session

    async def save_session(self, session: SessionState) -> None:
        await self.initialize()
        await self._store.save_session(session)
        await self._cache_session(session)

    async def list_sessions(self, user_id: str | None, limit: int = 30) -> list[dict[str, Any]]:
        await self.initialize()
        return await self._store.list_sessions(user_id, limit)

    async def load_turns(self, session_id: str) -> list[Turn]:
        await self.initialize()
        return await self._store.load_turns(session_id)

    async def rename_session(self, session_id: str, title: str) -> SessionState | None:
        session = await self.load_session(session_id)
        if session is None:
            return None
        session.title = title.strip()
        await self.save_session(session)
        return session

    async def _cache_session(self, session: SessionState) -> None:
        await self._event_bus.cache_session(
            session.session_id,
            session.model_dump(mode="json"),
            ttl_seconds=settings.runtime_session_cache_ttl_seconds,
        )

    async def _get_or_create_session(self, session_id: str | None, user_id: str | None) -> tuple[str, SessionState]:
        sid = session_id or str(uuid4())
        session = await self.load_session(sid)
        session = session or SessionState(session_id=sid, user_id=user_id)
        if user_id and not session.user_id:
            session.user_id = user_id
        return sid, session

    async def _get_or_create_profile(self, user_id: str | None) -> UserProfile | None:
        if not user_id:
            return None
        profile = await self._store.load_profile(user_id)
        return profile or UserProfile.create_default(user_id)

    async def _mine_profile(self, profile: UserProfile, session: SessionState) -> None:
        """Deterministic profile mining from constraint history (no LLM)."""
        constraints_list: list[dict] = []
        for turn in session.recent_turns:
            for item in turn.route_results:
                route = item.get("route") if isinstance(item, dict) else None
                if route:
                    for stop in route.get("stops", []):
                        category = stop.get("category", "")
                        if category and "菜" in category:
                            constraints_list.append({"preferred_cuisines": [category]})
        if session.current_constraints:
            constraints_list.append(session.current_constraints)
        if not constraints_list:
            return

        district_counts: dict[str, int] = {}
        cuisine_counts: dict[str, int] = {}
        budgets: list[int] = []
        times: list[int] = []
        for constraints in constraints_list[-10:]:
            district = constraints.get("district", "")
            if district:
                district_counts[district] = district_counts.get(district, 0) + 1
            for cuisine in constraints.get("preferred_cuisines") or []:
                cuisine_counts[str(cuisine)] = cuisine_counts.get(str(cuisine), 0) + 1
            if constraints.get("budget_per_person") is not None:
                budgets.append(int(constraints["budget_per_person"]))
            if constraints.get("time_budget_minutes") is not None:
                times.append(int(constraints["time_budget_minutes"]))
        if district_counts:
            profile.preferred_districts = sorted(district_counts, key=district_counts.get, reverse=True)
        if cuisine_counts:
            profile.preferred_cuisines = sorted(cuisine_counts, key=cuisine_counts.get, reverse=True)[:5]
        if budgets:
            profile.avg_budget_per_person = int(sum(budgets) / len(budgets))
        if times:
            profile.avg_time_budget_minutes = int(sum(times) / len(times))
        profile.total_turns += 1
        profile.updated_ts = utc_now_iso()

    async def _build_memory_context(self, session: SessionState, user_id: str | None) -> dict:
        profile = await self._get_or_create_profile(user_id)
        profile_dict = profile.model_dump(mode="json") if profile else {}
        return MemoryContext(
            session_id=session.session_id,
            dialog_summary=session.dialog_summary,
            current_route=session.current_route,
            current_constraints=session.current_constraints,
            route_intent=session.route_intent.model_dump(mode="json") if session.route_intent else None,
            assumptions=session.assumptions,
            confirmed_stop_ids=session.confirmed_stop_ids,
            rejected_poi_ids=session.rejected_poi_ids,
            recent_turns=[turn.model_dump(mode="json") for turn in session.recent_turns],
            user_profile=profile_dict,
        ).model_dump(mode="json")

    async def _save_session(self, session: SessionState, state: dict) -> None:
        route_results = state.get("route_results") or []
        if route_results and isinstance(route_results[0], dict):
            session.current_route = route_results[0].get("route") or route_results[0]
        if state.get("constraints"):
            session.current_constraints = state["constraints"]
        if state.get("assumptions"):
            session.assumptions = state["assumptions"]
        if state.get("route_intent"):
            session.route_intent = RouteIntent.model_validate(state["route_intent"])

        reply_type = infer_reply_type(state)
        session.add_turn(
            Turn(
                turn_id=state["turn_id"],
                user_query=state["user_query"],
                reply_type=reply_type,
                route_results=route_results,
                assumptions=state.get("assumptions", []),
                presentation=state.get("presentation"),
                assistant_message=(state.get("presentation") or {}).get("summary", ""),
            )
        )
        if reply_type == ReplyType.REJECT.value:
            session.mode = "planning"
        elif state.get("turn_mode") == "replan":
            session.mode = "replanning"
        elif reply_type == ReplyType.DIFF.value:
            session.mode = "reviewing"
        elif reply_type in (ReplyType.ROUTE.value, ReplyType.MULTI_ROUTE.value):
            session.mode = "reviewing"
        else:
            session.mode = "planning"

        session.dialog_summary, summary_meta = await summarize_session_with_meta(session)
        llm_call = llm_call_from_meta(
            "session_summary",
            summary_meta,
            fallback_used=bool(summary_meta.get("fallback_used")),
        )
        state.setdefault("llm_calls", []).append(llm_call)
        state.setdefault("phase_log", []).append(
            {
                "phase": "dialog_summary",
                "status": "completed",
                "ts": utc_now_iso(),
                "summary": "updated session summary",
                "llm_operation": llm_call["operation"],
                "llm_status": llm_call["status"],
            }
        )
        if not session.title:
            session.title = state["user_query"][:80]
        session.latest_response = response_snapshot(state)
        user_id = state.get("user_id")
        if user_id:
            profile = await self._get_or_create_profile(str(user_id))
            if profile:
                await self._mine_profile(profile, session)
                await self._store.save_profile(profile)
        await self.save_session(session)

    async def _emit(self, run_id: str, event: dict[str, Any]) -> dict[str, Any]:
        stored = await self._store.append_event(run_id, event)
        await self._event_bus.publish(run_id, stored)
        return stored

    async def _is_cancelled(self, run_id: str) -> bool:
        if await self._event_bus.is_cancelled(run_id):
            return True
        run = await self._store.get_run(run_id)
        return bool(run and run.get("status") == "cancelled")

    async def _prepare_run(
        self,
        query: str,
        *,
        user_id: str | None,
        user_lat: float | None,
        user_lng: float | None,
        session_id: str | None,
    ) -> tuple[dict, SessionState]:
        await self.initialize()
        sid, session = await self._get_or_create_session(session_id, user_id)
        initial = build_initial_state(
            query,
            user_id=user_id,
            user_lat=user_lat,
            user_lng=user_lng,
            session_id=sid,
        )
        if session.current_route:
            initial["session_current_route"] = session.current_route
        initial["memory_context"] = await self._build_memory_context(session, user_id)
        run_id = initial["run_id"]
        cancelled = await self._store.create_run(
            run_id,
            sid,
            {"query": query, "user_id": user_id, "lat": user_lat, "lng": user_lng},
        )
        for old_run_id in cancelled:
            await self._event_bus.cancel(old_run_id)
            await self._emit(old_run_id, {"phase": "runtime", "status": "cancelled", "summary": "superseded by a newer request"})
        await self._emit(run_id, {"phase": "runtime", "status": "queued", "summary": "run created"})
        return initial, session

    async def _execute_run(self, initial: dict, session: SessionState) -> dict:
        run_id = initial["run_id"]
        await self._store.set_run_status(run_id, "running")
        await self._emit(run_id, {"phase": "runtime", "status": "running", "summary": "plan run started"})
        final_state: dict = initial
        observed_phases = 0
        try:
            async for snapshot in self._agent.astream(initial, stream_mode="values"):
                final_state = snapshot
                phase_log = snapshot.get("phase_log") or []
                for phase in phase_log[observed_phases:]:
                    await self._emit(run_id, phase)
                observed_phases = len(phase_log)
                if await self._is_cancelled(run_id):
                    raise RunCancelled()

            await self._save_session(session, final_state)
            for phase in (final_state.get("phase_log") or [])[observed_phases:]:
                await self._emit(run_id, phase)
            usage = token_usage_from_calls(final_state.get("llm_calls") or [])
            final_status = "degraded" if final_state.get("degraded") else "completed"
            final_state["run_status"] = "completed" if final_status == "degraded" else final_status
            await self._store.set_run_status(run_id, final_status, result=final_state, token_usage=usage)
            await self._emit(
                run_id,
                {"phase": "complete", "status": final_status, "summary": "plan result ready", "data": {"run_status": final_status}},
            )
            return final_state
        except RunCancelled:
            final_state["run_status"] = "cancelled"
            await self._store.set_run_status(run_id, "cancelled", result=final_state, error_code="cancelled")
            await self._emit(run_id, {"phase": "complete", "status": "cancelled", "summary": "run cancelled"})
            return final_state
        except Exception as exc:
            logger.exception("plan run %s failed", run_id)
            final_state["run_status"] = "failed"
            final_state["error"] = "runtime_error"
            await self._store.set_run_status(run_id, "failed", result=final_state, error_code="runtime_error")
            await self._emit(run_id, {"phase": "complete", "status": "failed", "summary": "run failed", "data": {"error_code": "runtime_error"}})
            return final_state
        finally:
            self._tasks.pop(run_id, None)

    async def run_plan(
        self,
        query: str,
        *,
        user_id: str | None = None,
        user_lat: float | None = None,
        user_lng: float | None = None,
        session_id: str | None = None,
    ) -> dict:
        initial, session = await self._prepare_run(
            query,
            user_id=user_id,
            user_lat=user_lat,
            user_lng=user_lng,
            session_id=session_id,
        )
        final_state = await self._execute_run(initial, session)
        logger.info(
            "plan_run_observed %s",
            json.dumps(
                {
                    "run_id": final_state.get("run_id"),
                    "session_id": final_state.get("session_id"),
                    "run_status": final_state.get("run_status"),
                    "current_phase": final_state.get("current_phase"),
                    "token_usage": token_usage_from_calls(final_state.get("llm_calls") or []),
                    "phase_count": len(final_state.get("phase_log") or []),
                },
                ensure_ascii=False,
            ),
        )
        return final_state

    async def start_plan(self, query: str, **kwargs: Any) -> dict[str, str]:
        initial, session = await self._prepare_run(query, **kwargs)
        run_id = initial["run_id"]
        self._tasks[run_id] = asyncio.create_task(self._execute_run(initial, session), name=f"gentrip-run-{run_id}")
        return {"run_id": run_id, "session_id": initial["session_id"]}

    async def cancel_run(self, run_id: str) -> bool:
        await self.initialize()
        run = await self._store.get_run(run_id)
        if not run or run.get("status") in _TERMINAL_RUN_STATUSES:
            return False
        await self._event_bus.cancel(run_id)
        await self._store.set_run_status(run_id, "cancelled", error_code="cancelled")
        await self._emit(run_id, {"phase": "runtime", "status": "cancelled", "summary": "cancellation requested"})
        return True

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        await self.initialize()
        return await self._store.get_run(run_id)

    async def get_events_after(self, run_id: str, event_id: int) -> list[dict[str, Any]]:
        await self.initialize()
        return await self._store.get_events_after(run_id, event_id)

    async def subscribe_events(self, run_id: str):
        async for event in self._event_bus.subscribe(run_id):
            yield event
