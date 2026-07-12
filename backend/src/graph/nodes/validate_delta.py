"""[Replan 5] validate_delta — 仅校验变更部分。"""

from ...models.route import RoutePlan, ValidationReport
from ..state import GraphState, phase_update


def _parse_hhmm(value: object) -> int | None:
    if not isinstance(value, str) or ":" not in value:
        return None
    hour_text, minute_text = value.split(":", 1)
    if not (hour_text.isdigit() and minute_text.isdigit()):
        return None
    return int(hour_text) * 60 + int(minute_text)


async def validate_delta(state: GraphState) -> dict:
    operation = state.get("replan_operation") or {}
    constraints = state.get("constraints") or {}
    valid_routes = state.get("valid_routes") or []
    candidate_routes = state.get("candidate_routes") or []
    routes = candidate_routes or valid_routes
    retry_count = int(state.get("delta_retry_count", 0))

    if not routes:
        return phase_update(
            "validate_delta",
            summary=f"valid=False no routes retry={retry_count}",
            delta_valid=False,
            delta_retry_count=retry_count + 1,
            degraded=True,
        )

    route = RoutePlan.model_validate(routes[0]) if isinstance(routes[0], dict) else routes[0]
    if isinstance(route, dict):
        route = RoutePlan.model_validate(route)

    violations: list[str] = []
    budget = int(constraints.get("budget_per_person", 150))
    if route.estimated_cost_per_person > budget:
        violations.append(f"人均 {route.estimated_cost_per_person} 超过预算 {budget}")

    time_budget = constraints.get("time_budget_minutes")
    if time_budget and route.total_duration_min > int(time_budget):
        violations.append(f"总时长 {route.total_duration_min} 分钟超过预算 {int(time_budget)} 分钟")

    # Check timeline consistency for modified stops
    locked = set(state.get("locked_stop_indices") or [])
    for i, stop in enumerate(route.stops):
        if i in locked:
            continue  # skip locked stops
        arrival = _parse_hhmm(stop.arrival_time)
        departure = _parse_hhmm(stop.departure_time)
        if arrival is not None and departure is not None and departure < arrival:
            violations.append(f"第 {stop.sequence} 站离开时间早于到达时间")

    report = ValidationReport(
        route_id=route.plan_id,
        feasible=len(violations) == 0,
        violations=violations,
    )
    delta_valid = report.feasible
    return phase_update(
        "validate_delta",
        summary=f"valid={delta_valid} violations={len(violations)} retry={retry_count}",
        delta_valid=delta_valid,
        delta_retry_count=retry_count + 1 if not delta_valid else retry_count,
        validation_reports=[report.model_dump(mode="json")],
        valid_routes=[route.model_dump(mode="json")] if delta_valid else [],
        degraded=not delta_valid,
    )
