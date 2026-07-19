"""Turn orchestrator node — LLM-first classification with keyword fallback."""

from __future__ import annotations

from ...llm.turn_classify import classify_turn
from ...models.session import RouteIntent
from ..state import GraphState, llm_call_from_meta, phase_update

# Keyword fallback — used when LLM is disabled or fails
_NON_TRAVEL_KEYWORDS = (
    "股票", "基金", "天气", "新闻", "翻译", "写代码", "代码", "论文", "数学", "汇率",
)
_REVISION_KEYWORDS = (
    "换", "替换", "改成", "不要", "不去", "不想", "不喜欢",
    "删", "去掉", "跳过", "加", "增加", "追加", "再加",
    "改预算", "改时间", "换一家", "换一个", "不太行",
    "有没有别的", "有没有更", "重新推荐", "换一种",
    "还想去吃", "还想吃", "也想吃", "还要吃",
)


def _keyword_classify(query: str, has_current_route: bool) -> tuple[str, str]:
    """Fast keyword fallback when LLM is unavailable."""
    if any(k in query for k in _NON_TRAVEL_KEYWORDS):
        return "reject", "non_travel"
    if has_current_route and any(k in query for k in _REVISION_KEYWORDS):
        return "replan", "revision"
    return "plan", "new_plan"


def _primary_intent(query: str, mode: str) -> str:
    if mode == "reject":
        return "non_travel"
    if "逛吃" in query or ("逛" in query and ("吃" in query or "餐" in query)):
        return "逛吃"
    if any(w in query for w in ("展", "博物馆", "美术馆")):
        return "看展"
    if "亲子" in query:
        return "亲子"
    if any(w in query for w in ("附近", "周边")):
        return "附近推荐"
    return "路线规划"


def _route_summary(route: dict | None) -> str:
    """One-line summary of current route for LLM context."""
    if not route:
        return ""
    stops = route.get("stops", [])
    names = [s.get("poi_name", "?") for s in stops[:3]]
    dur = route.get("total_duration_min", "?")
    cost = route.get("estimated_cost_per_person", "?")
    return f"{len(stops)}站:{'→'.join(names)} {dur}分钟 人均{cost}元"


async def turn_orchestrate(state: GraphState) -> dict:
    query = state["user_query"].strip()
    has_route = bool(state.get("session_current_route"))
    route = state.get("session_current_route")
    memory = state.get("memory_context") or {}

    # --- LLM classification ---
    decision, llm_meta = await classify_turn(
        query,
        has_current_route=has_route,
        current_route_summary=_route_summary(route),
        current_constraints=memory.get("current_constraints"),
        dialog_summary=memory.get("dialog_summary", ""),
    )

    # --- Fallback to keywords if LLM skipped or failed ---
    if llm_meta.get("status") in ("skipped", "failed"):
        turn_mode, intent_type = _keyword_classify(query, has_route)
        primary_intent = _primary_intent(query, turn_mode)
    else:
        turn_mode = decision.turn_mode
        intent_type = "revision" if turn_mode == "replan" else (
            "non_travel" if turn_mode == "reject" else "new_plan"
        )
        # Validate: replan requires current route
        if turn_mode == "replan" and not has_route:
            turn_mode = "plan"
            intent_type = "new_plan"
        primary_intent = decision.primary_intent or _primary_intent(query, turn_mode)

    intent = RouteIntent(
        intent_type=intent_type,
        primary_intent=primary_intent,
        query_understanding=decision.query_understanding or f"{turn_mode}:{query[:50]}",
    )

    llm_call = llm_call_from_meta(
        "turn_orchestrate",
        llm_meta,
        fallback_used=bool(llm_meta.get("fallback_used")),
    )

    # Pass the ordered operation list to the replan subgraph. Keep the
    # singular field as a compatibility bridge for old callers and snapshots.
    replan_ops: list[dict] = []
    if turn_mode == "replan":
        source_ops = decision.replan_operations or ([decision.replan_operation] if decision.replan_operation else [])
        replan_ops = [{
            "type": op.type, "target_seq": op.target_seq,
            "target_category": op.target_category, "new_cuisine": op.new_cuisine,
            "after_seq": op.after_seq, "overrides": op.overrides,
        } for op in source_ops]
    replan_op = replan_ops[0] if len(replan_ops) == 1 else None

    return phase_update(
        "turn_orchestrate",
        summary=f"query={query[:40]} turn={turn_mode} has_route={has_route} llm={llm_meta.get('status','?')}",
        turn_mode=turn_mode,
        run_mode="replan" if turn_mode == "replan" else "plan",
        route_intent=intent.model_dump(mode="json"),
        replan_operation=replan_op,
        replan_operations=replan_ops,
        llm_calls=[llm_call],
    )
