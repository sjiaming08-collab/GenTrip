"""[1] constraint_extract — 约束提取 + 补全 assumptions。"""

from ...models.session import RouteIntent
from ...services.constraint_service import extract_with_meta
from ..state import GraphState, llm_call_from_meta, phase_update


async def constraint_extract(state: GraphState) -> dict:
    constraints, assumptions, llm_meta = await extract_with_meta(state)
    llm_call = llm_call_from_meta(
        "constraint_extract",
        llm_meta,
        fallback_used=bool(llm_meta.get("fallback_used")),
    )
    turn_decision = llm_meta.get("turn_decision") or {}
    # Constraint extraction describes the current utterance, but must not
    # erase the orchestrator's conversation relation during a broad replan.
    turn_mode = (
        "replan"
        if state.get("turn_relation") == "modify_current"
        else str(turn_decision.get("turn_mode") or state.get("turn_mode") or "plan")
    )
    route_intent = state.get("route_intent")
    if turn_decision:
        route_intent = RouteIntent(
            intent_type="non_travel" if turn_mode == "reject" else "new_plan",
            primary_intent=str(turn_decision.get("primary_intent") or "路线规划"),
            query_understanding=str(turn_decision.get("query_understanding") or ""),
        ).model_dump(mode="json")

    assumption_sources = {item.slot: item.source for item in assumptions}
    provenance = {
        field: assumption_sources.get(field, "current_query_explicit")
        for field, value in constraints.model_dump(mode="json").items()
        if field != "raw_query" and value not in (None, [], "")
    }

    update = phase_update(
        "constraint_extract",
        summary=(
            f"domains={[d.value for d in constraints.domains]} district={constraints.district} "
            f"budget={constraints.budget_per_person} duration={constraints.time_budget_minutes}min "
            f"start={constraints.start_at} return_by={constraints.return_by} "
            f"cuisines={constraints.preferred_cuisines} locations={constraints.location_mentions} "
            f"excluded={constraints.excluded_categories} "
            f"assumptions={len(assumptions)}"
        ),
        constraints=constraints.model_dump(mode="json"),
        constraint_provenance=provenance,
        assumptions=[a.model_dump(mode="json") for a in assumptions],
        constraint_embedding=None,
        plan_path="cold",
        turn_mode=turn_mode,
        route_intent=route_intent,
        llm_calls=[llm_call],
    )
    update["phase_log"][0].update({
        "llm_operation": llm_call["operation"],
        "llm_status": llm_call["status"],
        "constraint_source": "llm" if llm_call["status"] == "success" else "rule_fallback",
    })
    return update
