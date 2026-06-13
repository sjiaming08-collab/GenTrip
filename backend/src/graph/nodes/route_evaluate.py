"""[5] route_evaluate — 对合法路线打分排序。"""

from ...models.route import RoutePlan, ScoredRoute
from ..state import GraphState, phase_update


async def route_evaluate(state: GraphState) -> dict:
    constraints = state["constraints"]
    assert constraints is not None

    scored: list[ScoredRoute] = []
    budget = constraints["budget_per_person"]

    for raw in state["valid_routes"]:
        route = RoutePlan.model_validate(raw)
        avg_rating = sum(
            4.5 for _ in route.stops
        ) / max(len(route.stops), 1)

        quality = min(avg_rating / 5.0, 1.0)
        budget_gap = abs(route.estimated_cost_per_person - budget)
        execution = max(0.0, 1.0 - budget_gap / max(budget, 1))
        preference = 0.8
        final = 0.4 * execution + 0.4 * quality + 0.2 * preference

        scored.append(
            ScoredRoute(
                route=route,
                execution_score=round(execution, 3),
                quality_score=round(quality, 3),
                preference_score=round(preference, 3),
                final_score=round(final, 3),
            )
        )

    scored.sort(key=lambda item: item.final_score, reverse=True)
    for idx, item in enumerate(scored, start=1):
        item.rank = idx

    return phase_update(
        "route_evaluate",
        scored_routes=[s.model_dump(mode="json") for s in scored],
    )
