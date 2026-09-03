"""Turn orchestrator node — LLM-first classification with keyword fallback."""

from __future__ import annotations

import json
import re
from hashlib import sha256

from ...config import settings
from ...llm.turn_classify import LlmTurnDecision, classify_turn
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
_MEAL_SCOPE_KEYWORDS = (
    "早餐", "早饭", "午餐", "午饭", "中午", "晚餐", "晚饭", "晚上", "夜宵",
    "正餐", "简餐", "吃饭", "用餐", "餐厅", "饭店", "菜", "料理",
)
_ROUTE_DELTA_KEYWORDS = (
    "少走路", "少步行", "不排队", "别排队", "轻松一点", "紧凑一点",
    "早点出发", "晚点出发", "早点回来", "晚点回来", "前回来", "前结束",
)
_NEW_GOAL_KEYWORDS = (
    "另外一条", "另一条路线", "另做一条", "新建路线", "全新路线",
    "原来的不要了", "原路线不要了", "放弃原路线", "换个目的地",
)
_FULL_REBUILD_KEYWORDS = (
    "重新规划", "重新安排", "重做路线", "整体重做", "完全重做",
    "改预算", "预算改", "换到", "改区域", "换个区域", "换个风格",
    "改成亲子", "改成情侣", "改成朋友",
)


def _has_meal_slot(route: dict | None) -> bool:
    return any(
        stop.get("slot_role") == "meal"
        for stop in (route or {}).get("stops") or []
        if isinstance(stop, dict)
    )


def _is_contextual_adjustment(query: str, route: dict | None) -> bool:
    """Recognize a typed delta that only makes sense against the current route.

    This is deliberately narrower than generic travel intent detection. A saved
    route alone must not turn a complete new request into a replan, while a
    scoped meal/time/mobility fragment must survive an LLM outage.
    """
    if not route:
        return False
    if _has_explicit_revision(query):
        return True
    if _has_meal_slot(route) and any(keyword in query for keyword in _MEAL_SCOPE_KEYWORDS):
        return True
    return any(keyword in query for keyword in _ROUTE_DELTA_KEYWORDS)


def _keyword_classify(query: str, route: dict | None) -> tuple[str, str]:
    """Fast keyword fallback when LLM is unavailable."""
    if any(k in query for k in _NON_TRAVEL_KEYWORDS):
        return "reject", "non_travel"
    if _is_contextual_adjustment(query, route):
        return "replan", "revision"
    return "plan", "new_plan"


def _derive_relation_scope(
    query: str,
    route: dict | None,
    *,
    classified_mode: str,
    operations: list[dict] | None = None,
    suggested_relation: str | None = None,
    suggested_scope: str | None = None,
) -> tuple[str, str]:
    """Resolve conversation relation separately from recomputation cost.

    The LLM may propose an edit, but deterministic guards own whether an old
    route is actually in scope and how much of the planner must be rerun.
    """
    if classified_mode == "reject":
        return "reject", "none"
    if not route or not (route.get("stops") or []) or any(marker in query for marker in _NEW_GOAL_KEYWORDS):
        return "new_goal", "global_rebuild"

    contextual = _is_contextual_adjustment(query, route) or any(
        marker in query for marker in ("重新规划", "重新安排", "重做路线", "整体重做")
    )
    if suggested_relation == "modify_current" and not _looks_like_standalone_plan(query):
        contextual = True
    if not contextual:
        return "new_goal", "global_rebuild"

    ops = operations or []
    if any(item.get("type") == "change_pref" for item in ops) or any(
        marker in query for marker in _FULL_REBUILD_KEYWORDS
    ):
        return "modify_current", "global_rebuild"
    if any(marker in query for marker in _ROUTE_DELTA_KEYWORDS):
        return "modify_current", "schedule_route"
    if suggested_scope in {"slot_only", "schedule_route", "global_rebuild"}:
        return "modify_current", suggested_scope
    return "modify_current", "slot_only"


def _looks_like_standalone_plan(query: str) -> bool:
    signals = (
        bool(re.search(r"[\u4e00-\u9fff]{1,12}(?:省|市|区|县|镇)|附近|周边", query)),
        bool(re.search(r"\d+(?:\.\d+)?\s*(?:小时|分钟)|全天|一整天|玩一天", query)),
        bool(re.search(r"(?:人均|预算)\s*\d+|\d+\s*(?:元|块)", query)),
    )
    return sum(signals) >= 2


def _has_explicit_revision(query: str) -> bool:
    return any(keyword in query for keyword in _REVISION_KEYWORDS)


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


def _build_turn_context(state: GraphState) -> dict:
    memory = state.get("memory_context") or {}
    route = state.get("session_current_route") or memory.get("current_route") or {}
    return {
        "identity": {
            "tenant_id": state.get("tenant_id"),
            "session_id": state.get("session_id"),
            "turn_id": state.get("turn_id"),
            "session_version": int(memory.get("session_version") or 0),
        },
        "current_message": state.get("user_query") or "",
        "session_mode": memory.get("session_mode") or "planning",
        "current_route": route,
        "active_constraints": memory.get("current_constraints") or {},
        "confirmed_stop_ids": memory.get("confirmed_stop_ids") or [],
        "rejected_poi_ids": memory.get("rejected_poi_ids") or [],
        "pending_change": memory.get("pending_change"),
        "recent_turns": memory.get("recent_turns") or [],
        "dialog_summary": memory.get("dialog_summary") or "",
        "memory_facts": memory.get("memory_facts") or [],
        "user_profile": memory.get("user_profile") or {},
    }


def _normalize_operations(decision: LlmTurnDecision) -> list[dict]:
    source_ops = decision.replan_operations or (
        [decision.replan_operation] if decision.replan_operation else []
    )
    operations: list[dict] = []
    seen: set[str] = set()
    for op in source_ops:
        item = {
            "type": op.type,
            "target_seq": op.target_seq,
            "target_category": op.target_category,
            "new_cuisine": op.new_cuisine,
            "after_seq": op.after_seq,
            "overrides": op.overrides,
            "confidence": op.confidence,
            "source": "llm",
        }
        key = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if key in seen:
            continue
        seen.add(key)
        operations.append(item)
    return operations


async def turn_orchestrate(state: GraphState) -> dict:
    query = state["user_query"].strip()
    has_route = bool(state.get("session_current_route"))
    route = state.get("session_current_route")
    memory = state.get("memory_context") or {}
    turn_context = _build_turn_context(state)
    context_json = json.dumps(turn_context, ensure_ascii=False, sort_keys=True, default=str)
    context_meta = {
        "context_version": 1,
        "session_version": int(memory.get("session_version") or 0),
        "has_current_route": has_route,
        "route_stop_count": len((route or {}).get("stops") or []),
        "recent_turn_count": len(turn_context["recent_turns"]),
        "memory_fact_count": len(turn_context["memory_facts"]),
        "has_dialog_summary": bool(turn_context["dialog_summary"]),
        "context_digest": sha256(context_json.encode("utf-8")).hexdigest()[:16],
    }

    # Cold turns fuse intent classification into constraint extraction. Replan
    # keeps the context-aware classifier because it must resolve edit actions.
    deterministic_mode, _ = _keyword_classify(query, route)
    fused_cold_turn = (
        not has_route
        and deterministic_mode != "reject"
        and settings.llm_enabled
        and bool(settings.llm_api_key)
        and settings.constraint_extract_mode != "rule_only"
    )
    if not has_route and deterministic_mode == "reject":
        decision = LlmTurnDecision(
            turn_mode="reject",
            primary_intent="non_travel",
            query_understanding=f"reject:{query[:50]}",
        )
        llm_meta = {
            "operation": "turn_classify",
            "status": "skipped",
            "skip_reason": "explicit_non_travel",
        }
    elif fused_cold_turn:
        decision = LlmTurnDecision(
            turn_mode="plan",
            primary_intent=_primary_intent(query, "plan"),
            query_understanding=f"pending_constraint_understanding:{query[:40]}",
        )
        llm_meta = {
            "operation": "turn_classify",
            "status": "skipped",
            "skip_reason": "fused_with_constraint_extract",
        }
    else:
        decision, llm_meta = await classify_turn(
            query,
            has_current_route=has_route,
            current_route_summary=_route_summary(route),
            current_constraints=memory.get("current_constraints"),
            dialog_summary=memory.get("dialog_summary", ""),
            turn_context=turn_context,
        )

    # --- Fallback to keywords if LLM skipped or failed ---
    if llm_meta.get("status") in ("skipped", "failed"):
        turn_mode, intent_type = _keyword_classify(query, route)
        primary_intent = _primary_intent(query, turn_mode)
    else:
        turn_mode = decision.turn_mode
        intent_type = "revision" if turn_mode == "replan" else (
            "non_travel" if turn_mode == "reject" else "new_plan"
        )
        # A saved route alone is not consent to alter it. Fresh, standalone
        # requests must take the full planning path even if the classifier
        # over-predicts replan from the conversation context.
        if turn_mode == "replan" and _looks_like_standalone_plan(query):
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
    proposed_ops = _normalize_operations(decision) if turn_mode == "replan" else []
    turn_relation, recompute_scope = _derive_relation_scope(
        query,
        route,
        classified_mode=turn_mode,
        operations=proposed_ops,
        suggested_relation=decision.turn_relation,
        suggested_scope=decision.recompute_scope,
    )
    if settings.turn_router_v2_enabled:
        turn_mode = (
            "reject" if turn_relation == "reject"
            else "replan" if turn_relation == "modify_current"
            else "plan"
        )
        intent_type = (
            "non_travel" if turn_mode == "reject"
            else "revision" if turn_mode == "replan"
            else "new_plan"
        )
    else:
        turn_relation = "modify_current" if turn_mode == "replan" else (
            "reject" if turn_mode == "reject" else "new_goal"
        )
        recompute_scope = "slot_only" if turn_mode == "replan" else (
            "none" if turn_mode == "reject" else "global_rebuild"
        )
    replan_ops = proposed_ops if turn_relation == "modify_current" else []
    replan_op = replan_ops[0] if len(replan_ops) == 1 else None
    affected = sorted({
        int(seq)
        for seq in [
            *decision.affected_stop_seqs,
            *(item.get("target_seq") for item in replan_ops),
        ]
        if isinstance(seq, int) and seq > 0
    })
    turn_plan = {
        "turn_id": state.get("turn_id"),
        "mode": turn_mode,
        "turn_relation": turn_relation,
        "recompute_scope": recompute_scope,
        "objective": decision.objective or intent.query_understanding,
        "operations": replan_ops,
        "affected_stop_seqs": affected,
        "affected_slot_ids": list(dict.fromkeys(decision.affected_slot_ids)),
        "constraint_patch": decision.constraint_patch,
        "preserve_unmentioned_stops": (
            bool(decision.preserve_unmentioned_stops) if turn_mode == "replan" else False
        ),
        "preserve_confirmed_stops": (
            bool(decision.preserve_confirmed_stops) if turn_mode == "replan" else False
        ),
        "evidence": decision.evidence,
        "session_version": context_meta["session_version"],
        "context_digest": context_meta["context_digest"],
        "source": "llm" if llm_meta.get("status") == "success" else "rule_fallback",
        "confidence": min(
            (float(item.get("confidence") or 0.0) for item in replan_ops),
            default=1.0 if turn_mode != "replan" else 0.0,
        ),
    }

    return phase_update(
        "turn_orchestrate",
        summary=f"query={query[:40]} turn={turn_mode} relation={turn_relation} scope={recompute_scope} ops={len(replan_ops)} has_route={has_route} llm={llm_meta.get('status','?')}",
        turn_mode=turn_mode,
        run_mode="replan" if turn_mode == "replan" else "plan",
        turn_relation=turn_relation,
        recompute_scope=recompute_scope,
        constraint_patch=decision.constraint_patch,
        route_intent=intent.model_dump(mode="json"),
        turn_plan=turn_plan,
        turn_context_meta=context_meta,
        replan_operation=replan_op,
        replan_operations=replan_ops,
        llm_calls=[llm_call],
    )
