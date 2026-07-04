"""Turn orchestrator node."""

from __future__ import annotations

from ...models.session import RouteIntent
from ..state import GraphState, phase_update

_NON_TRAVEL_KEYWORDS = (
    "股票",
    "基金",
    "天气",
    "新闻",
    "翻译",
    "写代码",
    "代码",
    "论文",
    "数学",
    "汇率",
)
_REVISION_KEYWORDS = (
    "换",
    "替换",
    "改成",
    "不要",
    "删",
    "去掉",
    "加",
    "增加",
    "追加",
    "改预算",
    "改时间",
)
_NEW_PLAN_KEYWORDS = ("重新规划", "重新来", "换个方案", "再来一条")


def _primary_intent(query: str, mode: str) -> str:
    if mode == "reject":
        return "non_travel"
    if "逛吃" in query:
        return "逛吃"
    if any(word in query for word in ("展", "博物馆", "美术馆")):
        return "看展"
    if "亲子" in query:
        return "亲子"
    if any(word in query for word in ("附近", "周边")):
        return "附近推荐"
    return "路线规划"


async def turn_orchestrate(state: GraphState) -> dict:
    query = state["user_query"].strip()
    has_current_route = bool(state.get("session_current_route"))

    if any(keyword in query for keyword in _NON_TRAVEL_KEYWORDS):
        turn_mode = "reject"
        intent_type = "non_travel"
    elif has_current_route and any(keyword in query for keyword in _REVISION_KEYWORDS):
        turn_mode = "replan"
        intent_type = "revision"
    else:
        turn_mode = "plan"
        intent_type = "new_plan"
        if any(keyword in query for keyword in _NEW_PLAN_KEYWORDS):
            intent_type = "new_plan"

    intent = RouteIntent(
        intent_type=intent_type,
        primary_intent=_primary_intent(query, turn_mode),
        query_understanding=f"{turn_mode}:{query}",
    )

    return phase_update(
        "turn_orchestrate",
        summary=f"turn_mode={turn_mode}",
        turn_mode=turn_mode,
        run_mode="replan" if turn_mode == "replan" else "plan",
        route_intent=intent.model_dump(mode="json"),
    )
