"""[4] route_validate — hard constraint validation for generated routes."""

import re

from ...models.route import RoutePlan, ValidationReport
from ...services.constraint_rules import should_enforce_poi_count
from ...services.poi_hours import weekday_from_date
from ...services.planner_tools import PlanValidatorTool
from ..state import GraphState, phase_update


def _validate_route(route: RoutePlan, constraints: dict, poi_hours: dict[str, list[dict]], weekday: int | None) -> ValidationReport:
    judgement = PlanValidatorTool().run(
        route, constraints, poi_hours=poi_hours, weekday=weekday
    )
    violations = list(judgement.hard_violations)
    if len(route.legs) != max(0, len(route.stops) - 1):
        violations.append(
            f"路线有 {len(route.stops)} 站但交通段数量为 {len(route.legs)}"
        )
    for index, leg in enumerate(route.legs):
        if index + 1 >= len(route.stops):
            break
        if (
            leg.from_poi_id != route.stops[index].poi_id
            or leg.to_poi_id != route.stops[index + 1].poi_id
        ):
            violations.append(f"第 {index + 1} 段交通与相邻站点不一致")
    return ValidationReport(
        route_id=route.plan_id,
        feasible=not violations,
        violations=violations,
        risks=judgement.risks,
        optimistic_duration_min=judgement.optimistic_duration_min,
        expected_duration_min=judgement.expected_duration_min,
        conservative_duration_min=judgement.conservative_duration_min,
    )

async def route_validate(state: GraphState) -> dict:
    constraints = state["constraints"]
    assert constraints is not None
    validation_constraints = dict(constraints)
    compiled_atoms = (state.get("compiled_constraints") or {}).get("atoms") or []
    hard_fields = {
        str(item.get("field"))
        for item in compiled_atoms
        if item.get("strength") == "hard"
    }
    if compiled_atoms and "budget_per_person" not in hard_fields:
        validation_constraints["budget_per_person"] = 0
    if compiled_atoms and "time_scope" not in hard_fields:
        envelope = constraints.get("schedule_envelope") or {}
        validation_constraints["time_budget_minutes"] = envelope.get("max_duration_minutes")

    valid: list[dict] = []
    reports: list[dict] = []

    poi_hours = {
        str(poi.get("poi_id")): list(poi.get("opening_hours") or [])
        for poi in state.get("candidate_pois") or []
    }
    query = str(constraints.get("raw_query") or state.get("user_query") or "")
    explicit_count = bool(re.search(
        r"(?:\d{1,2}|[一二两三四五六七八九十]+)\s*个?\s*(?:活动|地点|景点|去处|项目|站)",
        query,
    ))
    generation_meta = state.get("route_generation_meta") or {}
    if generation_meta.get("mode") == "activity_blueprint":
        # Blueprint generation distinguishes an explicit activity count from a
        # duration-derived target. Do not re-harden the latter here.
        target_enforced = bool(generation_meta.get("target_stop_count_enforced"))
    else:
        target_enforced = (
            bool(generation_meta.get("target_stop_count_enforced"))
            or should_enforce_poi_count(query)
        )
    required_stops = int(generation_meta.get("minimum_stop_count") or 0) or None
    if target_enforced and required_stops is None:
        required_stops = int(
            generation_meta.get("target_stop_count")
            or constraints.get("poi_count")
            or 1
        )
    for raw in state["candidate_routes"]:
        route = RoutePlan.model_validate(raw)
        report = _validate_route(
            route,
            validation_constraints,
            poi_hours,
            weekday_from_date(state.get("input_ts")),
        )
        if required_stops is not None and len(route.stops) < required_stops:
            report.feasible = False
            requirement = "用户明确要求" if explicit_count else "目标"
            report.violations.append(
                f"路线仅有 {len(route.stops)} 站，少于{requirement}的 {required_stops} 站"
            )
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
