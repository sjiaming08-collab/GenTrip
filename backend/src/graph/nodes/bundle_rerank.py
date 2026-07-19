"""Reuse stored RouteBundle scores after current-request validation."""

from ...models.route import RoutePlan
from ..state import GraphState, phase_update


async def bundle_rerank(state: GraphState) -> dict:
    bundle = (state.get("bundle_candidates") or [{}])[0]
    by_plan_id = {
        str(item.get("route", {}).get("plan_id")): dict(item)
        for item in bundle.get("scored_routes") or []
    }
    scored: list[dict] = []
    for raw_route in state.get("valid_routes") or []:
        route = RoutePlan.model_validate(raw_route)
        stored = by_plan_id.get(route.plan_id)
        if stored:
            scored.append(stored)
    scored.sort(key=lambda item: float(item.get("final_score") or 0.0), reverse=True)
    for index, item in enumerate(scored, start=1):
        item["rank"] = index
    return phase_update(
        "bundle_rerank",
        summary=f"reranked {len(scored)} bundle routes",
        scored_routes=scored,
        route_evaluation_meta={"source": "bundle"},
    )
