"""Reject non-travel requests with a guided reply."""

from __future__ import annotations

from ...models.reply import AgentReplyMeta, ReplyType
from ..state import GraphState, phase_update


async def reject_reply(state: GraphState) -> dict:
    suggestions = ["附近有什么好玩的", "徐汇逛吃", "黄浦区看展览再喝咖啡"]
    presentation = {
        "title": "抱歉，我还不太擅长这类问题",
        "summary": "我可以帮你规划出行路线，试试这些：",
        "highlights": suggestions,
    }
    meta = AgentReplyMeta(
        plan_path=state.get("plan_path"),
        assumptions=state.get("assumptions", []),
        relaxed_constraints=state.get("relaxed_constraints", []),
        degraded=False,
        next_suggested_user_moves=suggestions,
    )
    return phase_update(
        "reject_reply",
        summary="non-travel request rejected",
        run_status="completed",
        planning_outcome="rejected",
        reply_type=ReplyType.REJECT.value,
        presentation=presentation,
        agent_reply_meta=meta.model_dump(mode="json"),
    )
