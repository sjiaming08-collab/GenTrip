"""[5] route_evaluate — 对合法路线打分排序。"""

from ...llm.route_evaluate import llm_score_routes_with_meta
from ...models.route import RoutePlan, ScoredRoute
from ..state import GraphState, llm_call_from_meta, phase_update


def _poi_quality_index(state: GraphState) -> dict[str, float]:
    index: dict[str, float] = {}
    for poi in state.get("candidate_pois") or []:
        poi_id = poi.get("poi_id")
        if poi_id:
            index[str(poi_id)] = float(poi.get("rating") or 4.0)
    return index


def _rule_scores(route: RoutePlan, constraints: dict, state: GraphState) -> tuple[float, float, float]:
    budget = int(constraints["budget_per_person"])
    budget_gap = max(0, route.estimated_cost_per_person - budget)
    budget_fit = max(0.0, 1.0 - budget_gap / max(budget, 1))

    time_budget = constraints.get("time_budget_minutes")
    if time_budget:
        time_gap = max(0, route.total_duration_min - int(time_budget))
        time_fit = max(0.0, 1.0 - time_gap / max(int(time_budget), 1))
    else:
        time_fit = 0.85
    execution = 0.55 * budget_fit + 0.45 * time_fit

    ratings = _poi_quality_index(state)
    stop_ratings = [ratings.get(stop.poi_id, 4.0) for stop in route.stops]
    avg_rating = sum(stop_ratings) / max(len(stop_ratings), 1)
    quality = min(avg_rating / 5.0, 1.0)

    preferred = constraints.get("preferred_cuisines") or []
    if preferred:
        matched = sum(1 for stop in route.stops if any(term in stop.category or term in stop.poi_name for term in preferred))
        preference = 0.55 + 0.45 * matched / max(len(route.stops), 1)
    else:
        domains = set(constraints.get("domains") or [])
        stop_categories = " ".join(stop.category for stop in route.stops)
        domain_hits = 0
        if "dining" in domains and any(word in stop_categories for word in ("菜", "餐", "咖啡", "甜品", "小吃")):
            domain_hits += 1
        if "sightseeing" in domains and any(word in stop_categories for word in ("博物馆", "公园", "观光", "文化")):
            domain_hits += 1
        if "shopping" in domains and "购物" in stop_categories:
            domain_hits += 1
        preference = 0.65 + min(domain_hits, max(len(domains), 1)) / max(len(domains), 1) * 0.25

    return round(execution, 3), round(quality, 3), round(min(preference, 1.0), 3)


async def route_evaluate(state: GraphState) -> dict:
    constraints = state["constraints"]
    assert constraints is not None

    routes = [RoutePlan.model_validate(raw) for raw in state["valid_routes"]]
    llm_scores, llm_meta = await llm_score_routes_with_meta(
        routes,
        constraints=constraints,
        user_query=state["user_query"],
        memory_context=state.get("memory_context"),
    )
    llm_call = llm_call_from_meta(
        "route_evaluate",
        llm_meta,
        fallback_used=bool(llm_meta.get("fallback_used")) or not bool(llm_scores),
    )

    scored: list[ScoredRoute] = []
    comments: dict[str, str] = {}

    for route in routes:
        llm_score = llm_scores.get(route.plan_id)
        if llm_score:
            execution = round(llm_score.execution, 3)
            quality = round(llm_score.quality, 3)
            preference = round(llm_score.preference, 3)
            comments[route.plan_id] = llm_score.comment
        else:
            execution, quality, preference = _rule_scores(route, constraints, state)
        final = 0.4 * execution + 0.4 * quality + 0.2 * preference

        scored.append(
            ScoredRoute(
                route=route,
                execution_score=execution,
                quality_score=quality,
                preference_score=preference,
                final_score=round(final, 3),
            )
        )

    scored.sort(key=lambda item: item.final_score, reverse=True)
    for idx, item in enumerate(scored, start=1):
        item.rank = idx

    source = "llm" if llm_scores else "rule"
    update = phase_update(
        "route_evaluate",
        summary=f"scored {len(scored)} routes via {source} top={scored[0].final_score if scored else 0:.2f}",
        scored_routes=[s.model_dump(mode="json") for s in scored],
        route_evaluation_meta={
            "source": source,
            "comments": comments,
        },
        llm_calls=[llm_call],
    )
    update["phase_log"][0].update({
        "score_source": source,
        "llm_operation": llm_call["operation"],
        "llm_status": llm_call["status"],
    })
    return update
