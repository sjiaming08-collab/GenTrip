"""[5] route_evaluate — 对合法路线打分排序。"""

import re

from ...config import settings
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


def _domain_coverage(route: RoutePlan, constraints: dict, state: GraphState) -> float:
    requested = set(constraints.get("domains") or [])
    if not requested:
        return 1.0
    poi_domains = {
        str(poi.get("poi_id")): str(poi.get("dimension") or "")
        for poi in state.get("candidate_pois") or []
    }
    covered = {poi_domains.get(stop.poi_id) for stop in route.stops}
    return len((covered - {""}) & requested) / len(requested)


def _skeleton_coverage(route: RoutePlan, state: GraphState) -> float:
    skeletons = (state.get("route_generation_meta") or {}).get("skeletons") or []
    if not skeletons:
        return 1.0
    explicit = [
        skeleton for skeleton in skeletons
        if any(slot.get("categories") for slot in skeleton)
    ]
    candidates = explicit or skeletons
    poi_domains = {
        str(poi.get("poi_id")): str(poi.get("dimension") or "")
        for poi in state.get("candidate_pois") or []
    }

    def score(skeleton: list[dict]) -> float:
        unused = set(range(len(route.stops)))
        matched = 0
        for slot in skeleton:
            categories = {str(item) for item in slot.get("categories") or []}
            domain = str(slot.get("domain") or "")
            found = next((
                index for index in unused
                if (not domain or poi_domains.get(route.stops[index].poi_id) == domain)
                and (not categories or route.stops[index].category in categories)
            ), None)
            if found is not None:
                unused.remove(found)
                matched += 1
        return matched / max(len(skeleton), 1)

    return max(score(skeleton) for skeleton in candidates)


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
    domain_coverage = _domain_coverage(route, constraints, state)
    skeletons = (state.get("route_generation_meta") or {}).get("skeletons") or []
    explicit_skeletons = [
        skeleton for skeleton in skeletons
        if any(slot.get("categories") for slot in skeleton)
    ]
    generation_meta = state.get("route_generation_meta") or {}
    generated_target = int(
        generation_meta.get("target_stop_count")
        or max((len(skeleton) for skeleton in skeletons), default=1)
    )
    query = str(constraints.get("raw_query") or state.get("user_query") or "")
    count_is_explicit = bool(re.search(
        r"(?:\d{1,2}|[一二两三四五六七八九十]+)\s*个?\s*(?:活动|地点|景点|去处|项目|站)",
        query,
    ))
    if count_is_explicit:
        target_stops = max(1, int(constraints.get("poi_count") or generated_target))
    elif explicit_skeletons:
        target_stops = max(len(skeleton) for skeleton in explicit_skeletons)
    else:
        target_stops = generated_target
    stop_coverage = min(len(route.stops) / target_stops, 1.0)
    skeleton_coverage = _skeleton_coverage(route, state)
    if preferred:
        matched_preferences = sum(
            1
            for term in preferred
            if any(term in stop.category or term in stop.poi_name for stop in route.stops)
        )
        cuisine_coverage = matched_preferences / len(preferred)
        preference = 0.05 + 0.10 * cuisine_coverage + 0.10 * domain_coverage + 0.15 * stop_coverage + 0.60 * skeleton_coverage
    else:
        preference = 0.10 + 0.25 * domain_coverage + 0.45 * stop_coverage + 0.20 * skeleton_coverage

    return round(execution, 3), round(quality, 3), round(min(preference, 1.0), 3)


async def route_evaluate(state: GraphState) -> dict:
    constraints = state["constraints"]
    assert constraints is not None

    routes = [RoutePlan.model_validate(raw) for raw in state["valid_routes"]]
    if settings.route_evaluate_mode != "rule_only":
        llm_scores, llm_meta = await llm_score_routes_with_meta(
            routes,
            constraints=constraints,
            user_query=state["user_query"],
            memory_context=state.get("memory_context"),
        )
    else:
        llm_scores = {}
        llm_meta = {
            "operation": "route_evaluate",
            "status": "skipped",
            "skip_reason": "rule_only_mode",
        }
    llm_call = llm_call_from_meta(
        "route_evaluate",
        llm_meta,
        fallback_used=bool(llm_meta.get("fallback_used")),
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
