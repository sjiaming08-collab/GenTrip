"""LLM 约束提取调用。"""

from pydantic import ValidationError

from ..graph.state import GraphState
from .client import get_llm_client
from .exceptions import LLMParseError
from .prompts.constraint_extract import SYSTEM_PROMPT, build_user_prompt
from .schemas import ConstraintExtractResult


async def llm_extract_constraint(state: GraphState) -> ConstraintExtractResult:
    client = get_llm_client()
    user_prompt = build_user_prompt(
        state["user_query"],
        user_lat=state.get("user_lat"),
        user_lng=state.get("user_lng"),
    )
    raw = await client.chat_json(SYSTEM_PROMPT, user_prompt)
    try:
        return ConstraintExtractResult.model_validate(raw)
    except ValidationError as exc:
        raise LLMParseError(f"schema 校验失败: {exc}") from exc
