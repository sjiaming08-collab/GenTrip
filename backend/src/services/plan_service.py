"""Plan 业务编排。"""

from __future__ import annotations

import json
import logging

from uuid import uuid4

from ..graph.plan_graph import create_plan_agent
from ..graph.state import build_initial_state, llm_call_from_meta, token_usage_from_calls, utc_now_iso
from ..llm.session_summary import summarize_session_with_meta
from ..models.memory import MemoryContext
from ..models.reply import ReplyType
from ..models.session import RouteIntent, SessionState, Turn


logger = logging.getLogger(__name__)


def infer_reply_type(state: dict) -> str:
    if state.get("turn_mode") == "reject" or state.get("reply_type") == ReplyType.REJECT.value:
        return ReplyType.REJECT.value
    if state.get("degraded"):
        return ReplyType.DEGRADED_ROUTE.value
    if len(state.get("route_results") or []) >= 2:
        return ReplyType.MULTI_ROUTE.value
    return ReplyType.ROUTE.value


class PlanService:
    def __init__(self) -> None:
        self._agent = create_plan_agent()
        self._sessions: dict[str, SessionState] = {}

    def _get_or_create_session(self, session_id: str | None) -> tuple[str, SessionState]:
        if session_id and session_id in self._sessions:
            return session_id, self._sessions[session_id]
        sid = session_id or str(uuid4())
        session = SessionState(session_id=sid)
        self._sessions[sid] = session
        return sid, session

    def get_session(self, session_id: str) -> SessionState | None:
        return self._sessions.get(session_id)

    def _build_memory_context(self, session: SessionState) -> dict:
        return MemoryContext(
            session_id=session.session_id,
            dialog_summary=session.dialog_summary,
            current_route=session.current_route,
            current_constraints=session.current_constraints,
            route_intent=session.route_intent.model_dump(mode="json") if session.route_intent else None,
            assumptions=session.assumptions,
            recent_turns=[turn.model_dump(mode="json") for turn in session.recent_turns],
            user_profile={},
        ).model_dump(mode="json")

    async def _save_session(self, session: SessionState, state: dict) -> None:
        route_results = state.get("route_results") or []
        if route_results:
            first = route_results[0]
            if isinstance(first, dict):
                session.current_route = first.get("route") or first

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
            )
        )
        if reply_type == ReplyType.REJECT.value:
            session.mode = "planning"
        elif state.get("run_mode") == "replan":
            session.mode = "replanning"
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

    async def run_plan(
        self,
        query: str,
        *,
        user_id: str | None = None,
        user_lat: float | None = None,
        user_lng: float | None = None,
        session_id: str | None = None,
    ) -> dict:
        sid, session = self._get_or_create_session(session_id)
        initial = build_initial_state(
            query,
            user_id=user_id,
            user_lat=user_lat,
            user_lng=user_lng,
            session_id=sid,
        )
        if session.current_route:
            initial["session_current_route"] = session.current_route
        initial["memory_context"] = self._build_memory_context(session)

        final_state = await self._agent.ainvoke(initial)
        await self._save_session(session, final_state)
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
