"""[4] route_validate — hard constraint validation for generated routes."""

from ...models.route import RoutePlan, ValidationReport
from ...services.poi_hours import weekday_from_date
from ...services.route_judge import judge_route
from ..state import GraphState, phase_update


def _validate_route(route: RoutePlan, constraints: dict, poi_hours: dict[str, list[dict]], weekday: int | None) -> ValidationReport:
    judgement = judge_route(route, constraints, poi_hours=poi_hours, weekday=weekday)
    return ValidationReport(
        route_id=route.plan_id,
        feasible=judgement.feasible,
        violations=judgement.hard_violations,
        risks=judgement.risks,
        optimistic_duration_min=judgement.optimistic_duration_min,
        expected_duration_min=judgement.expected_duration_min,
        conservative_duration_min=judgement.conservative_duration_min,
    )

async def route_validate(state: GraphState) -> dict:
    constraints = state["constraints"]
    assert constraints is not None

    valid: list[dict] = []
    reports: list[dict] = []

    poi_hours = {
        str(poi.get("poi_id")): list(poi.get("opening_hours") or [])
        for poi in state.get("candidate_pois") or []
    }
    for raw in state["candidate_routes"]:
        route = RoutePlan.model_validate(raw)
        report = _validate_route(route, constraints, poi_hours, weekday_from_date(state.get("input_ts")))
        reports.append(report.model_dump(mode="json"))
        if report.feasible:
            valid.append(route.model_dump(mode="json"))

    update = phase_update(
        "route_validate",
        summary=f"valid={len(valid)} violations={sum(len(r.get('violations') or []) for r in reports)}",
        valid_routes=valid,
        validation_reports=reports,
        relaxed_constraints=[],
        degraded=False,
    )
    update["phase_log"][0].update({
        "valid_count": len(valid),
        "violation_count": sum(len(r.get("violations") or []) for r in reports),
        "degraded": False,
    })
    return update
