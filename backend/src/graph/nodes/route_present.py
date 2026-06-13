"""[6] route_present — Top-K 输出。"""

from ...models.route import (
    Presentation,
    RoutePlanResult,
    RouteScores,
    RouteSource,
    ScoredRoute,
)
from ..state import GraphState, phase_update

TOP_K = 2


async def route_present(state: GraphState) -> dict:
    scored = [ScoredRoute.model_validate(item) for item in state["scored_routes"]]
    if not scored:
        return phase_update(
            "route_present",
            run_status="failed",
            error="no_scored_routes",
        )

    top = scored[:TOP_K]
    results: list[RoutePlanResult] = []
    for item in top:
        results.append(
            RoutePlanResult(
                route=item.route,
                source=RouteSource.DEGRADED if state.get("degraded") else RouteSource.COLD_GENERATED,
                rank=item.rank,
                scores=RouteScores(
                    execution=item.execution_score,
                    quality=item.quality_score,
                    final=item.final_score,
                ),
            )
        )

    best = top[0]
    presentation = Presentation(
        title=f"为您推荐的{best.route.plan_name}",
        summary=best.route.summary,
        highlights=[
            f"共 {len(best.route.stops)} 站，预计 {best.route.total_duration_min} 分钟",
            f"预估人均 {best.route.estimated_cost_per_person} 元",
        ],
    )

    if state.get("assumptions"):
        presentation.highlights.extend(
            a["message"] for a in state["assumptions"][:2]
        )

    return phase_update(
        "route_present",
        route_results=[r.model_dump(mode="json") for r in results],
        presentation=presentation.model_dump(mode="json"),
        run_status="completed",
    )
