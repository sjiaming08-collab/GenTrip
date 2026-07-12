"""LLM turn classification — Plan / Replan / Reject routing with operation details."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError

from ..config import settings
from .client import get_llm_client
from .exceptions import LLMError
from .prompts.turn_classify import SYSTEM_PROMPT, build_user_prompt


class LlmReplanOp(BaseModel):
    """Replan operation details output by LLM."""
    type: str = "replace"          # "delete" | "replace" | "add" | "change_pref"
    target_seq: int | None = None  # 第N站 (1-indexed)
    target_category: str | None = None  # category to delete/replace/add
    new_cuisine: str | None = None
    after_seq: int | None = None   # for add operations
    overrides: dict[str, Any] = Field(default_factory=dict)  # for change_pref


class LlmTurnDecision(BaseModel):
    turn_mode: str = Field(default="plan")  # "plan" | "replan" | "reject"
    primary_intent: str = ""
    query_understanding: str = ""
    reason: str = ""
    replan_operation: LlmReplanOp | None = None


async def classify_turn(
    query: str,
    *,
    has_current_route: bool = False,
    current_route_summary: str = "",
    current_constraints: dict[str, Any] | None = None,
    dialog_summary: str = "",
) -> tuple[LlmTurnDecision, dict]:
    """LLM-based turn classification + replan operation details. Returns decision + telemetry meta."""
    if not settings.llm_enabled or not settings.llm_api_key:
        return LlmTurnDecision(), {"operation": "turn_classify", "status": "skipped"}

    user_prompt = build_user_prompt(
        query,
        has_current_route=has_current_route,
        current_route_summary=current_route_summary,
        current_constraints=current_constraints,
        dialog_summary=dialog_summary,
    )

    try:
        client = get_llm_client()
        if hasattr(client, "chat_json_with_meta"):
            raw, meta = await client.chat_json_with_meta(
                SYSTEM_PROMPT, user_prompt, operation="turn_classify"
            )
        else:
            raw = await client.chat_json(SYSTEM_PROMPT, user_prompt)
            meta = {"operation": "turn_classify", "status": "success"}
        decision = LlmTurnDecision.model_validate(raw)
        return decision, meta
    except (LLMError, ValidationError):
        return LlmTurnDecision(), {"operation": "turn_classify", "status": "failed", "fallback_used": True}
