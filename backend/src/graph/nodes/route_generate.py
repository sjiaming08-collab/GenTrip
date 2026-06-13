"""[3] route_generate — 从候选 POI 生成多条候选路线（Mock）。"""

from ...models.route import RoutePlan, RouteStop, ScoredPoi
from ..state import GraphState, phase_update

VISIT_DURATION = 60
TRAVEL_GAP = 20


def _build_route(
    name: str,
    summary: str,
    pois: list[ScoredPoi],
    start_hour: int = 14,
) -> RoutePlan:
    stops: list[RouteStop] = []
    cursor_min = start_hour * 60
    for idx, poi in enumerate(pois, start=1):
        travel = 0 if idx == 1 else TRAVEL_GAP
        arrival = cursor_min + travel
        departure = arrival + VISIT_DURATION
        stops.append(
            RouteStop(
                sequence=idx,
                poi_id=poi.poi_id,
                poi_name=poi.name,
                category=poi.category,
                arrival_time=f"{arrival // 60:02d}:{arrival % 60:02d}",
                departure_time=f"{departure // 60:02d}:{departure % 60:02d}",
                visit_duration_min=VISIT_DURATION,
                travel_time_from_prev_min=travel,
            )
        )
        cursor_min = departure

    paid_prices = [p.price_per_person for p in pois if p.price_per_person > 0]
    avg_cost = int(sum(paid_prices) / len(paid_prices)) if paid_prices else 0

    return RoutePlan(
        plan_name=name,
        summary=summary,
        stops=stops,
        total_duration_min=cursor_min - start_hour * 60,
        estimated_cost_per_person=avg_cost,
    )


async def route_generate(state: GraphState) -> dict:
    constraints = state["constraints"]
    assert constraints is not None

    pois = [ScoredPoi.model_validate(p) for p in state["candidate_pois"]]
    poi_count = min(constraints["poi_count"], len(pois))
    poi_count = max(poi_count, 1)

    routes: list[RoutePlan] = []

    primary = pois[:poi_count]
    routes.append(
        _build_route(
            name=f"{constraints['district']}精选路线",
            summary=f"{len(primary)} 站 · 人均约 {constraints['budget_per_person']} 元",
            pois=primary,
        )
    )

    if len(pois) >= poi_count + 1:
        alt = pois[1 : poi_count + 1]
        routes.append(
            _build_route(
                name=f"{constraints['district']}备选路线",
                summary="备选组合，偏重高评分点位",
                pois=alt,
                start_hour=15,
            )
        )

    return phase_update(
        "route_generate",
        candidate_routes=[r.model_dump(mode="json") for r in routes],
    )
