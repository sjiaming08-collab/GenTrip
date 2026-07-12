"""LLM-backed session summary with deterministic fallback."""

from __future__ import annotations

from typing import Any

from ..config import settings
from ..models.session import SessionState
from .client import get_llm_client
from .exceptions import LLMError, LLMParseError
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
    return {
        "previous_summary": session.dialog_summary,
        "current_route": session.current_route,
        "assumptions": session.assumptions,
        "recent_turns": [turn.model_dump(mode="json") for turn in session.recent_turns[-5:]],
    }



async def summarize_session_with_meta(session: SessionState) -> tuple[str, dict]:
    if not settings.llm_enabled or not settings.llm_api_key:
        return fallback_dialog_summary(session), {"operation": "session_summary", "status": "skipped"}

    client = get_llm_client()
    try:
        if hasattr(client, "chat_json_with_meta"):
            raw, meta = await client.chat_json_with_meta(
                SYSTEM_PROMPT,
                str(_summary_payload(session)),
                operation="session_summary",
            )
        else:
            raw = await client.chat_json(SYSTEM_PROMPT, str(_summary_payload(session)))
            meta = {"operation": "session_summary", "status": "success"}
    except LLMError:
        return fallback_dialog_summary(session), {"operation": "session_summary", "status": "failed", "fallback_used": True}

    summary = raw.get("dialog_summary")
    if not isinstance(summary, str) or not summary.strip():
        _ = LLMParseError(f"session summary missing dialog_summary: {raw}")
        return fallback_dialog_summary(session), {"operation": "session_summary", "status": "failed", "fallback_used": True}
    return summary.strip(), meta


async def summarize_session(session: SessionState) -> str:
    summary, _meta = await summarize_session_with_meta(session)
    return summary
