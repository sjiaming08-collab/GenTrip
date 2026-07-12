"""LLM 约束提取调用。"""

from pydantic import ValidationError

from ..graph.state import GraphState
from .client import get_llm_client
from .exceptions import LLMParseError
from .prompts.constraint_extract import SYSTEM_PROMPT, build_user_prompt
from .schemas import ConstraintExtractResult


async def llm_extract_constraint(state: GraphState) -> ConstraintExtractResult:
    result, _meta = await llm_extract_constraint_with_meta(state)
    return result


async def llm_extract_constraint_with_meta(state: GraphState) -> tuple[ConstraintExtractResult, dict]:
    client = get_llm_client()
    user_prompt = build_user_prompt(
        state["user_query"],
        user_lat=state.get("user_lat"),
        user_lng=state.get("user_lng"),
        memory_context=state.get("memory_context"),
    )
    try:
        if hasattr(client, "chat_json_with_meta"):
            raw, meta = await client.chat_json_with_meta(
                SYSTEM_PROMPT, user_prompt, operation="constraint_extract"
            )
        else:
            raw = await client.chat_json(SYSTEM_PROMPT, user_prompt)
            meta = {"operation": "constraint_extract", "status": "success"}
        result = ConstraintExtractResult.model_validate(raw)
        return result, meta
    except ValidationError as exc:
        raise LLMParseError(f"schema 校验失败: {exc}") from exc
