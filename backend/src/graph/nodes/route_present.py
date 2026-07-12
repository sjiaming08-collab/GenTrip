"""[6] route_present — Top-K 输出。"""

from ...llm.route_present import llm_present_route_with_meta
from ...models.route import (
    Presentation,
    RoutePlanResult,
    RouteScores,
    RouteSource,
    ScoredRoute,
)
from ..state import GraphState, llm_call_from_meta, phase_update

TOP_K = 2


def _fallback_presentation(best: ScoredRoute, state: GraphState) -> Presentation:
    presentation = Presentation(
        title=f"为您推荐的{best.route.plan_name}",
        summary=best.route.summary,
        highlights=[
            f"共 {len(best.route.stops)} 站，预计 {best.route.total_duration_min} 分钟",
            f"预估人均 {best.route.estimated_cost_per_person} 元",
        ],
    )

    comments = (state.get("route_evaluation_meta") or {}).get("comments") or {}
    comment = comments.get(best.route.plan_id)
    if comment:
        presentation.highlights.append(comment)

    if state.get("assumptions"):
        presentation.highlights.extend(
            a["message"] for a in state["assumptions"][:2]
        )
    return presentation


async def route_present(state: GraphState) -> dict:
    scored = [ScoredRoute.model_validate(item) for item in state["scored_routes"]]
    if not scored:
        return phase_update(
            "route_present",
            status="failed",
            summary="no scored routes",
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

    presentation, llm_meta = await llm_present_route_with_meta(
        results,
        user_query=state["user_query"],
        assumptions=state.get("assumptions", []),
        relaxed_constraints=state.get("relaxed_constraints", []),
        evaluation_meta=state.get("route_evaluation_meta"),
        memory_context=state.get("memory_context"),
    )
    source = "llm"
    if presentation is None:
        presentation = _fallback_presentation(top[0], state)
        source = "template"
    llm_call = llm_call_from_meta(
        "route_present",
        llm_meta,
        fallback_used=bool(llm_meta.get("fallback_used")) or source == "template",
    )

    update = phase_update(
        "route_present",
        summary=f"presented {len(results)} routes via {source} reply={state.get('reply_type','route')} plan={top[0].route.plan_name if top else 'none'} stops={len(top[0].route.stops) if top else 0}",
        route_results=[r.model_dump(mode="json") for r in results],
        presentation=presentation.model_dump(mode="json"),
        run_status="completed",
        llm_calls=[llm_call],
    )
    update["phase_log"][0].update({
        "presentation_source": source,
        "llm_operation": llm_call["operation"],
        "llm_status": llm_call["status"],
    })
    return update
