"""LLM-backed session summary with deterministic fallback."""

from __future__ import annotations

import json
from typing import Any

from ..config import settings
from ..models.session import SessionState
from .client import get_llm_client
from .exceptions import LLMError, LLMParseError, failure_meta
from .prompts.session_summary import SYSTEM_PROMPT


def fallback_dialog_summary(session: SessionState) -> str:
    turns = session.recent_turns[-3:]
    if not turns:
        return session.dialog_summary
    last = turns[-1]
    parts = [f"最近用户需求：{last.user_query}"]
    if session.assumptions:
        messages = [item.get("message") for item in session.assumptions[:3] if item.get("message")]
        if messages:
            parts.append("系统假设：" + "；".join(messages))
    if session.current_route:
        name = session.current_route.get("plan_name") or "当前路线"
        parts.append(f"当前路线：{name}")
    return "，".join(parts)


def _summary_payload(session: SessionState) -> dict[str, Any]:
    route = session.current_route or {}
    return {
        "previous_summary": session.dialog_summary,
        "current_constraints": session.current_constraints,
        "current_route": {
            "plan_name": route.get("plan_name"),
            "stops": [
                {"name": stop.get("poi_name"), "category": stop.get("category")}
                for stop in (route.get("stops") or [])[:6]
            ],
        },
        "assumptions": [
            {"slot": item.get("slot"), "message": item.get("message")}
            for item in session.assumptions[:6]
        ],
        "memory_facts": [
            {"slot": item.get("slot"), "value": item.get("value")}
            for item in session.memory_facts[-12:]
        ],
        "recent_turns": [
            {
                "user_query": turn.user_query,
                "reply_type": turn.reply_type,
                "assistant_message": turn.assistant_message,
            }
            for turn in session.recent_turns[-5:]
        ],
    }



async def summarize_session_with_meta(session: SessionState) -> tuple[str, dict]:
    if settings.session_summary_mode == "rule_only":
        return fallback_dialog_summary(session), {
            "operation": "session_summary",
            "status": "skipped",
            "skip_reason": "deterministic_summary",
        }
    if not settings.llm_enabled or not settings.llm_api_key:
        return fallback_dialog_summary(session), {"operation": "session_summary", "status": "skipped"}

    client = get_llm_client()
    try:
        if hasattr(client, "chat_json_with_meta"):
            raw, meta = await client.chat_json_with_meta(
                SYSTEM_PROMPT,
                json.dumps(_summary_payload(session), ensure_ascii=False, separators=(",", ":")),
                operation="session_summary",
            )
        else:
            raw = await client.chat_json(SYSTEM_PROMPT, str(_summary_payload(session)))
            meta = {"operation": "session_summary", "status": "success"}
    except LLMError as exc:
        return fallback_dialog_summary(session), failure_meta("session_summary", exc)

    summary = raw.get("dialog_summary")
    if not isinstance(summary, str) or not summary.strip():
        _ = LLMParseError(f"session summary missing dialog_summary: {raw}")
        return fallback_dialog_summary(session), {"operation": "session_summary", "status": "failed", "fallback_used": True}
    return summary.strip(), meta


async def summarize_session(session: SessionState) -> str:
    summary, _meta = await summarize_session_with_meta(session)
    return summary
