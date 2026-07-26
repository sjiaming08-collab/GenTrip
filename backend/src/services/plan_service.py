"""Plan orchestration, durable run lifecycle, and live phase events."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone
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
from ..observability.metrics import runtime_metrics
from ..observability.tracing import finish_plan_run_span, inject_trace_context, start_plan_run_span
from ..runtime.events import RuntimeEventBus
from ..runtime.stage_observer import reset_stage_emitter, set_stage_emitter
from ..runtime.store import DEFAULT_TENANT_ID, RuntimeStore, SessionVersionConflict, TenantRunCapacityExceeded, build_runtime_store
from ..runtime.task_queue import DeadLetterPlanRun, PlanTaskQueue, QueueUnavailable, RedisPlanTaskQueue


logger = logging.getLogger(__name__)
_TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled", "degraded", "timed_out", "interrupted"}


def _tenant(value: str | None) -> str:
    return (value or DEFAULT_TENANT_ID).strip() or DEFAULT_TENANT_ID


class RunCancelled(Exception):
    """Raised between graph nodes after a user cancels or supersedes a run."""


class QueuedRunFailed(RuntimeError):
    """Signals that a worker should retry a graph run that reached failed state."""


def degraded_reasons_from_state(state: dict[str, Any]) -> list[str]:
    """Collect user-safe feasibility reasons without exposing prompts or secrets."""
    reasons = [str(item) for item in state.get("relaxed_constraints") or []]
    pending = state.get("pending_change") or {}
    reasons.extend(str(item) for item in pending.get("reasons") or [])
    reasons.extend(
        str(item)
        for report in state.get("validation_reports") or []
        for item in report.get("violations") or []
    )
    return list(dict.fromkeys(reason for reason in reasons if reason))[:8]


def next_suggested_moves(state: dict[str, Any], reply_type: str | None = None) -> list[str]:
    reply = reply_type or infer_reply_type(state)
    decision = state.get("planning_decision") or {}
    option_labels = [str(item.get("label")) for item in decision.get("options") or [] if item.get("label")]
    if option_labels:
        return option_labels[:3]
    if state.get("planning_outcome") == "change_rejected":
        return ["放宽时间后再试", "换一种同类选择", "保留原路线"]
    if reply == ReplyType.REJECT.value:
        return ["附近有什么好玩的", "徐汇逛吃", "黄浦区看展览再喝咖啡"]
    if reply in {ReplyType.CLARIFICATION.value, ReplyType.INFEASIBLE.value}:
        return ["延长可用时间", "减少一个活动", "提高预算"]
    return ["换个预算", "增加一家咖啡", "换到静安区"]


def infer_reply_type(state: dict) -> str:
    if state.get("turn_mode") == "reject" or state.get("reply_type") == ReplyType.REJECT.value:
        return ReplyType.REJECT.value
    if state.get("reply_type") == ReplyType.DIFF.value:
        return ReplyType.DIFF.value
    if state.get("reply_type") == ReplyType.CLARIFICATION.value:
        return ReplyType.CLARIFICATION.value
    if state.get("reply_type") == ReplyType.INFEASIBLE.value:
        return ReplyType.INFEASIBLE.value
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
        "planning_outcome": state.get("planning_outcome", "pending"),
        "meta": {
            "plan_path": state.get("plan_path"),
            "assumptions": state.get("assumptions", []),
            "relaxed_constraints": state.get("relaxed_constraints", []),
            "degraded": bool(state.get("degraded", False)),
            "next_suggested_user_moves": next_suggested_moves(state, reply_type),
            "phase_log": state.get("phase_log") or [],
            "llm_calls": llm_calls,
            "tool_calls": state.get("tool_calls") or [],
            "data_sources": sorted({str(item.get("source")) for item in (state.get("tool_calls") or []) if item.get("source")}),
            "degraded_reasons": degraded_reasons_from_state(state),
            "planning_decision": state.get("planning_decision"),
            "pending_change": state.get("pending_change"),
            "rejected_change": state.get("rejected_change"),
            "token_usage": token_usage_from_calls(llm_calls),
            "debug_trace_id": state.get("trace_id") or state.get("run_id"),
        },
    }


class PlanService:
    def __init__(
        self,
        store: RuntimeStore | None = None,
        event_bus: RuntimeEventBus | None = None,
        task_queue: PlanTaskQueue | None = None,
    ) -> None:
        self._agent = create_plan_agent()
        self._store = store or build_runtime_store(settings.database_url)
        self._event_bus = event_bus or RuntimeEventBus(settings.redis_url)
        # Compatibility for existing isolated tests that seed the in-memory store directly.
        self._sessions = getattr(self._store, "sessions", {})
        self._profiles = getattr(self._store, "profiles", {})
        self._tasks: dict[str, asyncio.Task[dict]] = {}
        self._task_queue = task_queue or RedisPlanTaskQueue()
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

    def get_session(self, session_id: str, *, tenant_id: str | None = None) -> SessionState | None:
        """Backward-compatible synchronous lookup for the in-memory test store."""
        if self.persistent:
            raise RuntimeError("use load_session() when the persistent runtime is enabled")
        session = self._sessions.get((_tenant(tenant_id), session_id))
        if session is None and _tenant(tenant_id) == DEFAULT_TENANT_ID:
            session = self._sessions.get(session_id)
        return session

    async def load_session(self, session_id: str, *, tenant_id: str | None = None) -> SessionState | None:
        await self.initialize()
        tenant = _tenant(tenant_id)
        cached = await self._event_bus.get_session(tenant, session_id)
        if cached:
            try:
                session = SessionState.model_validate(cached)
                if session.tenant_id == tenant:
                    return session
            except Exception:
                pass
        session = await self._store.load_session(tenant, session_id)
        if session:
            await self._cache_session(session)
        return session

    async def save_session(self, session: SessionState) -> None:
        await self.initialize()
        await self._store.save_session(session)
        await self._cache_session(session)

    async def list_sessions(self, user_id: str | None, limit: int = 30, *, tenant_id: str | None = None) -> list[dict[str, Any]]:
        await self.initialize()
        return await self._store.list_sessions(_tenant(tenant_id), user_id, limit)

    async def load_turns(self, session_id: str, *, tenant_id: str | None = None) -> list[Turn]:
        await self.initialize()
        return await self._store.load_turns(_tenant(tenant_id), session_id)

    async def rename_session(self, session_id: str, title: str, *, tenant_id: str | None = None) -> SessionState | None:
        session = await self.load_session(session_id, tenant_id=tenant_id)
        if session is None:
            return None
        session.title = title.strip()
        await self.save_session(session)
        return session

    async def delete_session(self, session_id: str, *, tenant_id: str | None = None) -> str:
        await self.initialize()
        tenant = _tenant(tenant_id)
        outcome = await self._store.delete_session(tenant, session_id)
        if outcome == "deleted":
            self._sessions.pop((tenant, session_id), None)
            await self._event_bus.delete_session(tenant, session_id)
        return outcome

    @staticmethod
    def _feedback_route_poi_ids(session: SessionState, route_id: str | None) -> list[str]:
        if not route_id:
            return []
        candidates = [session.current_route]
        candidates.extend((session.latest_response or {}).get("route_results") or [])
        for candidate in candidates:
            route = candidate.get("route") if isinstance(candidate, dict) and candidate.get("route") else candidate
            if not isinstance(route, dict) or str(route.get("plan_id")) != route_id:
                continue
            return [str(stop.get("poi_id")) for stop in route.get("stops") or [] if stop.get("poi_id")]
        return []

    @staticmethod
    def _update_profile_pois(profile: UserProfile, *, liked: list[str] = [], avoided: list[str] = []) -> None:
        profile.liked_poi_ids = [poi for poi in profile.liked_poi_ids if poi not in avoided]
        profile.avoided_poi_ids = [poi for poi in profile.avoided_poi_ids if poi not in liked]
        profile.liked_poi_ids = list(dict.fromkeys([*profile.liked_poi_ids, *liked]))[-100:]
        profile.avoided_poi_ids = list(dict.fromkeys([*profile.avoided_poi_ids, *avoided]))[-100:]
        profile.updated_ts = utc_now_iso()

    async def apply_feedback(
        self,
        session_id: str,
        *,
        tenant_id: str | None = None,
        action: str,
        poi_id: str | None = None,
        route_id: str | None = None,
        score: int | None = None,
        comment: str | None = None,
        overturned_assumption: str | None = None,
    ) -> SessionState | None:
        session = await self.load_session(session_id, tenant_id=tenant_id)
        if session is None:
            return None
        liked: list[str] = []
        avoided: list[str] = []
        if action == "confirm" and poi_id:
            session.mode = "completed"
            if poi_id not in session.confirmed_stop_ids:
                session.confirmed_stop_ids.append(poi_id)
            liked = [poi_id]
        elif action == "reject_poi" and poi_id:
            if poi_id not in session.rejected_poi_ids:
                session.rejected_poi_ids.append(poi_id)
            avoided = [poi_id]
        elif action == "rate" and route_id:
            session.route_feedback.append({"route_id": route_id, "score": score, "comment": comment})
            session.route_feedback = session.route_feedback[-50:]
            route_pois = self._feedback_route_poi_ids(session, route_id)
            if score is not None and score >= 4:
                liked = route_pois
            elif score is not None and score <= 2:
                avoided = route_pois
        elif action == "overturn_assumption" and overturned_assumption:
            session.mode = "replanning"
            if overturned_assumption not in session.overridden_slots:
                session.overridden_slots.append(overturned_assumption)
        elif action not in {"confirm", "reject_poi", "rate", "overturn_assumption"}:
            raise ValueError("unsupported_feedback_action")

        if session.user_id and (liked or avoided):
            profile = await self._get_or_create_profile(session.tenant_id, session.user_id)
            if profile:
                self._update_profile_pois(profile, liked=liked, avoided=avoided)
                await self._store.save_profile(session.tenant_id, profile)
        await self.save_session(session)
        return session

    async def _cache_session(self, session: SessionState) -> None:
        await self._event_bus.cache_session(
            session.tenant_id,
            session.session_id,
            session.model_dump(mode="json"),
            ttl_seconds=settings.runtime_session_cache_ttl_seconds,
        )

    async def _get_or_create_session(self, session_id: str | None, user_id: str | None, tenant_id: str) -> tuple[str, SessionState]:
        sid = session_id or str(uuid4())
        session = await self.load_session(sid, tenant_id=tenant_id)
        session = session or SessionState(session_id=sid, tenant_id=tenant_id, user_id=user_id)
        if user_id and not session.user_id:
            session.user_id = user_id
        return sid, session

    async def _get_or_create_profile(self, tenant_id: str, user_id: str | None) -> UserProfile | None:
        if not user_id:
            return None
        profile = await self._store.load_profile(tenant_id, user_id)
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
        profile = await self._get_or_create_profile(session.tenant_id, user_id)
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
            memory_facts=self._active_memory_facts(session.memory_facts),
            user_profile=profile_dict,
        ).model_dump(mode="json")

    @staticmethod
    def _active_memory_facts(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        active: list[dict[str, Any]] = []
        for fact in facts:
            try:
                expires_at = datetime.fromisoformat(str(fact.get("expires_at") or "").replace("Z", "+00:00"))
            except ValueError:
                continue
            if expires_at > now and fact.get("source") == "explicit_user":
                active.append(fact)
        return active[-24:]

    @staticmethod
    def _explicit_memory_facts(query: str, turn_id: str) -> list[dict[str, Any]]:
        from .constraint_rules import (
            detect_budget, detect_district, detect_excluded_categories, detect_minutes,
            detect_preferred_cuisines, detect_queue_tolerance_minutes, detect_return_by, detect_start_at,
        )

        values: dict[str, Any] = {
            "district": detect_district(query),
            "budget_per_person": detect_budget(query),
            "time_budget_minutes": detect_minutes(query),
            "start_at": detect_start_at(query),
            "return_by": detect_return_by(query),
            "queue_tolerance_minutes": detect_queue_tolerance_minutes(query),
            "preferred_cuisines": detect_preferred_cuisines(query),
            "excluded_categories": detect_excluded_categories(query),
        }
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(days=30)).isoformat()
        return [
            {
                "slot": slot,
                "value": value,
                "source": "explicit_user",
                "confidence": "high",
                "turn_id": turn_id,
                "created_at": now.isoformat(),
                "expires_at": expires_at,
            }
            for slot, value in values.items()
            if value not in (None, [], "")
        ]

    @staticmethod
    def _merge_memory_facts(existing: list[dict[str, Any]], new_facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_slot = {str(fact.get("slot")): fact for fact in existing if fact.get("slot")}
        for fact in new_facts:
            by_slot[str(fact["slot"])] = fact
        return list(by_slot.values())[-24:]

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
        session.pending_change = state.get("pending_change")
        if state.get("rejected_change"):
            session.rejected_change = state.get("rejected_change")

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
        session.memory_facts = self._merge_memory_facts(
            session.memory_facts,
            self._explicit_memory_facts(state["user_query"], state["turn_id"]),
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
            profile = await self._get_or_create_profile(session.tenant_id, str(user_id))
            if profile:
                await self._mine_profile(profile, session)
                await self._store.save_profile(session.tenant_id, profile)
        await self.save_session(session)

    async def _emit(self, tenant_id: str, run_id: str, event: dict[str, Any]) -> dict[str, Any]:
        stored = await self._store.append_event(tenant_id, run_id, event)
        await self._event_bus.publish(run_id, stored)
        return stored

    @staticmethod
    def _phase_event(snapshot: dict[str, Any], phase: dict[str, Any]) -> dict[str, Any]:
        """Build a safe, self-contained event for the live runtime console.

        The event deliberately contains operational metadata only. Prompts,
        model responses, and credentials never enter the persisted event log.
        """
        llm_calls = snapshot.get("llm_calls") or []
        tool_calls = snapshot.get("tool_calls") or []
        data = {
            "current_phase": snapshot.get("current_phase"),
            "plan_path": snapshot.get("plan_path"),
            "turn_mode": snapshot.get("turn_mode"),
            "planning_outcome": snapshot.get("planning_outcome", "pending"),
            "planning_decision": snapshot.get("planning_decision"),
            "pending_change": snapshot.get("pending_change"),
            "rejected_change": snapshot.get("rejected_change"),
            "degraded": bool(snapshot.get("degraded", False)),
            "relaxed_constraints": snapshot.get("relaxed_constraints") or [],
            "degraded_reasons": degraded_reasons_from_state(snapshot),
            "llm_calls": llm_calls,
            "tool_calls": tool_calls,
            "token_usage": token_usage_from_calls(llm_calls),
            "data_sources": sorted({
                str(item.get("source"))
                for item in tool_calls
                if item.get("source")
            }),
        }
        if phase.get("phase") == "constraint_extract":
            constraints = snapshot.get("constraints") or {}
            data["extracted_constraints"] = {
                key: constraints.get(key)
                for key in (
                    "district",
                    "domains",
                    "budget_per_person",
                    "time_budget_minutes",
                    "start_at",
                    "return_by",
                    "queue_tolerance_minutes",
                    "poi_count",
                    "preferred_cuisines",
                    "excluded_categories",
                )
                if constraints.get(key) is not None
            }
            data["constraint_source"] = phase.get("constraint_source", "rule_fallback")
        return {
            **phase,
            "data": data,
        }

    @staticmethod
    def _checkpoint_state(snapshot: dict[str, Any]) -> dict[str, Any]:
        """Persist bounded recovery evidence, not the raw LLM conversation."""
        route_results = snapshot.get("route_results") or []
        return {
            "current_phase": snapshot.get("current_phase"),
            "plan_path": snapshot.get("plan_path"),
            "turn_mode": snapshot.get("turn_mode"),
            "planning_outcome": snapshot.get("planning_outcome", "pending"),
            "degraded": bool(snapshot.get("degraded", False)),
            "phase_log": list(snapshot.get("phase_log") or [])[-20:],
            "llm_calls": list(snapshot.get("llm_calls") or [])[-10:],
            "tool_calls": list(snapshot.get("tool_calls") or [])[-20:],
            "route_ids": [
                str((item.get("route") or item).get("plan_id", ""))
                for item in route_results
                if isinstance(item, dict) and isinstance(item.get("route") or item, dict)
            ][:10],
            "validation_reports": list(snapshot.get("validation_reports") or [])[-10:],
            "relaxed_constraints": list(snapshot.get("relaxed_constraints") or [])[-20:],
        }

    async def _is_cancelled(self, tenant_id: str, run_id: str) -> bool:
        if await self._event_bus.is_cancelled(run_id):
            return True
        run = await self._store.get_run(tenant_id, run_id)
        return bool(run and run.get("status") == "cancelled")

    async def _prepare_run(
        self,
        query: str,
        *,
        user_id: str | None = None,
        user_lat: float | None = None,
        user_lng: float | None = None,
        session_id: str | None = None,
        tenant_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[dict, SessionState]:
        await self.initialize()
        tenant = _tenant(tenant_id)
        sid, session = await self._get_or_create_session(session_id, user_id, tenant)
        initial = build_initial_state(
            query,
            user_id=user_id,
            user_lat=user_lat,
            user_lng=user_lng,
            session_id=sid,
            tenant_id=tenant,
        )
        if session.current_route:
            initial["session_current_route"] = session.current_route
        initial["memory_context"] = await self._build_memory_context(session, user_id)
        run_id = initial["run_id"]
        cancelled = await self._store.create_run(
            run_id,
            tenant,
            sid,
            {"query": query, "user_id": user_id, "lat": user_lat, "lng": user_lng, "idempotency_key": idempotency_key},
        )
        for old_run_id in cancelled:
            await self._event_bus.cancel(old_run_id)
            await self._emit(tenant, old_run_id, {"phase": "runtime", "status": "cancelled", "summary": "superseded by a newer request"})
        await self._emit(tenant, run_id, {"phase": "runtime", "status": "queued", "summary": "run created"})
        return initial, session

    async def _execute_run(self, initial: dict, session: SessionState) -> dict:
        run_id = initial["run_id"]
        tenant_id = session.tenant_id
        span, span_token, trace_id = start_plan_run_span(initial, tenant_id=tenant_id)
        initial["trace_id"] = trace_id
        started_at = time.perf_counter()
        terminal_status = "failed"
        await self._store.set_run_status(run_id, "running")
        await self._emit(tenant_id, run_id, {"phase": "runtime", "status": "running", "summary": "plan run started"})
        stage_token = set_stage_emitter(lambda event: self._emit(tenant_id, run_id, event))
        final_state: dict = initial
        observed_phases = 0
        try:
            async with asyncio.timeout(settings.runtime_run_deadline_seconds):
                async for snapshot in self._agent.astream(initial, stream_mode="values"):
                    final_state = snapshot
                    phase_log = snapshot.get("phase_log") or []
                    for phase in phase_log[observed_phases:]:
                        await self._emit(tenant_id, run_id, self._phase_event(snapshot, phase))
                    observed_phases = len(phase_log)
                    if phase_log:
                        latest_phase = phase_log[-1]
                        await self._store.save_run_checkpoint(
                            tenant_id,
                            run_id,
                            str(latest_phase.get("phase") or snapshot.get("current_phase") or "unknown"),
                            observed_phases,
                            self._checkpoint_state(snapshot),
                        )
                    if await self._is_cancelled(tenant_id, run_id):
                        raise RunCancelled()

            await self._save_session(session, final_state)
            for phase in (final_state.get("phase_log") or [])[observed_phases:]:
                await self._emit(tenant_id, run_id, self._phase_event(final_state, phase))
            usage = token_usage_from_calls(final_state.get("llm_calls") or [])
            final_status = "degraded" if final_state.get("degraded") else "completed"
            terminal_status = final_status
            final_state["run_status"] = "completed" if final_status == "degraded" else final_status
            await self._store.set_run_status(run_id, final_status, result=final_state, token_usage=usage)
            await self._emit(
                tenant_id,
                run_id,
                {"phase": "complete", "status": final_status, "summary": "plan result ready", "data": {"run_status": final_status}},
            )
            return final_state
        except SessionVersionConflict:
            terminal_status = "cancelled"
            final_state["run_status"] = "cancelled"
            final_state["error"] = "superseded"
            await self._store.set_run_status(run_id, "cancelled", result=final_state, error_code="superseded")
            await self._emit(tenant_id, run_id, {"phase": "complete", "status": "cancelled", "summary": "session superseded by a newer run", "data": {"error_code": "superseded"}})
            return final_state
        except RunCancelled:
            terminal_status = "cancelled"
            final_state["run_status"] = "cancelled"
            await self._store.set_run_status(run_id, "cancelled", result=final_state, error_code="cancelled")
            await self._emit(tenant_id, run_id, {"phase": "complete", "status": "cancelled", "summary": "run cancelled"})
            return final_state
        except TimeoutError:
            terminal_status = "timed_out"
            final_state["run_status"] = "timed_out"
            final_state["error"] = "run_deadline_exceeded"
            await self._store.set_run_status(run_id, "timed_out", result=final_state, error_code="run_deadline_exceeded")
            await self._emit(tenant_id, run_id, {"phase": "complete", "status": "timed_out", "summary": "run deadline exceeded", "data": {"error_code": "run_deadline_exceeded"}})
            return final_state
        except Exception as exc:
            terminal_status = "failed"
            logger.exception("plan run %s failed", run_id)
            final_state["run_status"] = "failed"
            final_state["error"] = "runtime_error"
            await self._store.set_run_status(run_id, "failed", result=final_state, error_code="runtime_error")
            await self._emit(
                tenant_id,
                run_id,
                {
                    "phase": "complete",
                    "status": "failed",
                    "summary": "run failed",
                    "data": {"error_code": "runtime_error", "error_type": type(exc).__name__},
                },
            )
            return final_state
        finally:
            reset_stage_emitter(stage_token)
            runtime_metrics.record_run(final_state, terminal_status, time.perf_counter() - started_at)
            finish_plan_run_span(
                span,
                span_token,
                status=terminal_status,
                phase_count=len(final_state.get("phase_log") or []),
                token_usage=token_usage_from_calls(final_state.get("llm_calls") or []),
            )
            self._tasks.pop(run_id, None)

    async def run_plan(
        self,
        query: str,
        *,
        user_id: str | None = None,
        user_lat: float | None = None,
        user_lng: float | None = None,
        session_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict:
        initial, session = await self._prepare_run(
            query,
            user_id=user_id,
            user_lat=user_lat,
            user_lng=user_lng,
            session_id=session_id,
            tenant_id=tenant_id,
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
        session_id = kwargs.get("session_id")
        idempotency_key = kwargs.get("idempotency_key")
        tenant_id = _tenant(kwargs.get("tenant_id"))
        if session_id and idempotency_key:
            await self.initialize()
            existing = await self._store.find_run_by_idempotency(tenant_id, str(session_id), str(idempotency_key))
            if existing and existing.get("status") not in {"failed", "cancelled"}:
                return {"run_id": str(existing["run_id"]), "session_id": str(existing["session_id"])}
        initial, session = await self._prepare_run(query, **kwargs)
        run_id = initial["run_id"]
        if settings.runtime_execution_mode == "redis_stream":
            initial["_trace_context"] = inject_trace_context()
            await self.save_session(session)
            try:
                await self._task_queue.enqueue(initial, session.model_dump(mode="json"))
            except QueueUnavailable:
                await self._store.set_run_status(run_id, "failed", error_code="queue_unavailable")
                await self._store.release_run_idempotency(session.tenant_id, run_id)
                await self._emit(session.tenant_id, run_id, {"phase": "runtime", "status": "failed", "summary": "plan queue unavailable"})
                raise
        else:
            self._tasks[run_id] = asyncio.create_task(self._execute_run(initial, session), name=f"gentrip-run-{run_id}")
        return {"run_id": run_id, "session_id": initial["session_id"]}

    async def execute_queued_run(self, initial: dict[str, Any], session_payload: dict[str, Any]) -> dict[str, Any] | None:
        """Execute a durable queue payload in a worker process."""
        if not initial or not session_payload:
            return None
        session = SessionState.model_validate(session_payload)
        run_id = str(initial.get("run_id") or "")
        run = await self._store.get_run(session.tenant_id, run_id)
        if run is None or run.get("status") == "cancelled":
            return None
        final_state = await self._execute_run(initial, session)
        if final_state.get("run_status") == "failed":
            raise QueuedRunFailed(str(final_state.get("error") or "plan_run_failed"))
        return final_state

    async def fail_queued_run(self, initial: dict[str, Any], session_payload: dict[str, Any], *, error_code: str) -> None:
        """Persist a terminal worker failure after the queue has exhausted retries."""
        if not initial or not session_payload:
            return
        session = SessionState.model_validate(session_payload)
        run_id = str(initial.get("run_id") or "")
        if not run_id:
            return
        await self._store.set_run_status(run_id, "failed", error_code=error_code)
        await self._store.release_run_idempotency(session.tenant_id, run_id)
        await self._emit(
            session.tenant_id,
            run_id,
            {"phase": "complete", "status": "failed", "summary": "worker retries exhausted", "data": {"error_code": error_code}},
        )

    async def cancel_run(self, run_id: str, *, tenant_id: str | None = None) -> bool:
        await self.initialize()
        tenant = _tenant(tenant_id)
        run = await self._store.get_run(tenant, run_id)
        if not run or run.get("status") in _TERMINAL_RUN_STATUSES:
            return False
        await self._event_bus.cancel(run_id)
        await self._store.set_run_status(run_id, "cancelled", error_code="cancelled")
        await self._emit(tenant, run_id, {"phase": "runtime", "status": "cancelled", "summary": "cancellation requested"})
        return True

    async def get_run(self, run_id: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
        await self.initialize()
        return await self._store.get_run(_tenant(tenant_id), run_id)

    async def list_run_checkpoints(self, run_id: str, *, tenant_id: str | None = None) -> list[dict[str, Any]]:
        await self.initialize()
        return await self._store.list_run_checkpoints(_tenant(tenant_id), run_id)

    async def list_dead_letters(self, *, limit: int = 100) -> list[DeadLetterPlanRun]:
        if not isinstance(self._task_queue, RedisPlanTaskQueue):
            raise QueueUnavailable("DLQ operations require redis_stream execution")
        return await self._task_queue.list_dead_letters(limit=limit)

    async def replay_dead_letter(self, message_id: str) -> str:
        if not isinstance(self._task_queue, RedisPlanTaskQueue):
            raise QueueUnavailable("DLQ operations require redis_stream execution")
        return await self._task_queue.replay_dead_letter(message_id)

    async def get_events_after(self, run_id: str, event_id: int, *, tenant_id: str | None = None) -> list[dict[str, Any]]:
        await self.initialize()
        return await self._store.get_events_after(_tenant(tenant_id), run_id, event_id)

    async def subscribe_events(self, run_id: str):
        async for event in self._event_bus.subscribe(run_id):
            yield event
