"""LLM turn classification — Plan / Replan / Reject routing with operation details."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from ..config import settings
from .client import get_llm_client
from .exceptions import LLMError, failure_meta
from .prompts.turn_classify import SYSTEM_PROMPT, build_user_prompt


class LlmReplanOp(BaseModel):
    """Replan operation details output by LLM."""
    type: Literal["delete", "replace", "add", "change_pref"] = "replace"
    target_seq: int | None = Field(default=None, ge=1)  # 第N站 (1-indexed)
    target_category: str | None = None  # category to delete/replace/add
    new_cuisine: str | None = None
    after_seq: int | None = Field(default=None, ge=0)   # for add operations
    overrides: dict[str, Any] = Field(default_factory=dict)  # for change_pref
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class LlmTurnDecision(BaseModel):
    turn_mode: Literal["plan", "replan", "reject"] = "plan"
    turn_relation: Literal["new_goal", "modify_current", "reject"] | None = None
    recompute_scope: Literal["slot_only", "schedule_route", "global_rebuild", "none"] | None = None
    primary_intent: str = ""
    query_understanding: str = ""
    reason: str = ""
    objective: str = ""
    affected_stop_seqs: list[int] = Field(default_factory=list)
    affected_slot_ids: list[str] = Field(default_factory=list)
    preserve_unmentioned_stops: bool = True
    preserve_confirmed_stops: bool = True
    constraint_patch: dict[str, Any] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)
    replan_operations: list[LlmReplanOp] = Field(default_factory=list)
    replan_operation: LlmReplanOp | None = None


async def classify_turn(
    query: str,
    *,
    has_current_route: bool = False,
    current_route_summary: str = "",
    current_constraints: dict[str, Any] | None = None,
    dialog_summary: str = "",
    turn_context: dict[str, Any] | None = None,
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
        turn_context=turn_context,
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
    except (LLMError, ValidationError) as exc:
        return LlmTurnDecision(), failure_meta("turn_classify", exc)
