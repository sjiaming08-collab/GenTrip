"""[4] route_validate — hard constraint validation for generated routes."""

from ...models.route import RoutePlan, ValidationReport
from ..state import GraphState, phase_update

MAX_REASONABLE_TRAVEL_MIN = 90


def _parse_hhmm(value: object) -> int | None:
    if not isinstance(value, str) or ":" not in value:
        return None
    hour_text, minute_text = value.split(":", 1)
    if not (hour_text.isdigit() and minute_text.isdigit()):
        return None
    hour = int(hour_text)
    minute = int(minute_text)
    if hour < 0 or hour > 47 or minute < 0 or minute > 59:
        return None
    return hour * 60 + minute


def _route_end_minute(route: RoutePlan) -> int | None:
    if not route.stops:
        return None
    return _parse_hhmm(route.stops[-1].departure_time)


def _validate_stop_timeline(route: RoutePlan, violations: list[str]) -> None:
    previous_departure: int | None = None
    for stop in route.stops:
        arrival = _parse_hhmm(stop.arrival_time)
        departure = _parse_hhmm(stop.departure_time)
        if arrival is None or departure is None:
            violations.append(f"第 {stop.sequence} 站时间格式非法")
            continue
        if departure < arrival:
            violations.append(f"第 {stop.sequence} 站离开时间早于到达时间")
        if stop.travel_time_from_prev_min < 0:
            violations.append(f"第 {stop.sequence} 站交通时间为负数")
        if stop.travel_time_from_prev_min > MAX_REASONABLE_TRAVEL_MIN:
            violations.append(f"第 {stop.sequence} 站交通时间 {stop.travel_time_from_prev_min} 分钟过长")
        if previous_departure is not None and arrival < previous_departure + stop.travel_time_from_prev_min:
            violations.append(f"第 {stop.sequence} 站到达时间早于上一站出发加交通时间")
        previous_departure = departure


def _validate_route(route: RoutePlan, constraints: dict) -> ValidationReport:
    violations: list[str] = []

    budget = int(constraints["budget_per_person"])
    if route.estimated_cost_per_person > budget:
        violations.append(f"人均 {route.estimated_cost_per_person} 超过预算 {budget}")

    time_budget = constraints.get("time_budget_minutes")
    if time_budget and route.total_duration_min > int(time_budget):
        violations.append(f"总时长 {route.total_duration_min} 分钟超过预算 {int(time_budget)} 分钟")

    return_by = _parse_hhmm(constraints.get("return_by"))
    route_end = _route_end_minute(route)
    if return_by is not None and route_end is not None and route_end > return_by:
        violations.append(f"结束时间 {route.stops[-1].departure_time} 晚于返回时间 {constraints['return_by']}")

    start_at = _parse_hhmm(constraints.get("start_at"))
    first_arrival = _parse_hhmm(route.stops[0].arrival_time) if route.stops else None
    if start_at is not None and first_arrival is not None and first_arrival < start_at:
        violations.append(f"首站到达时间 {route.stops[0].arrival_time} 早于出发时间 {constraints['start_at']}")

    queue_tolerance = constraints.get("queue_tolerance_minutes")
    if queue_tolerance is not None:
        for stop in route.stops:
            if stop.queue_wait_min > int(queue_tolerance):
                violations.append(f"第 {stop.sequence} 站预计排队 {stop.queue_wait_min} 分钟超过上限 {int(queue_tolerance)} 分钟")

    _validate_stop_timeline(route, violations)

    return ValidationReport(
        route_id=route.plan_id,
        feasible=len(violations) == 0,
        violations=violations,
    )


def _route_violation_rank(route: RoutePlan, constraints: dict, report: ValidationReport) -> tuple[int, int, int]:
    budget = int(constraints["budget_per_person"])
    over_budget = max(0, route.estimated_cost_per_person - budget)

    time_budget = constraints.get("time_budget_minutes")
    over_time = max(0, route.total_duration_min - int(time_budget)) if time_budget else 0

    return_by = _parse_hhmm(constraints.get("return_by"))
    route_end = _route_end_minute(route)
    over_return = max(0, route_end - return_by) if return_by is not None and route_end is not None else 0

    severity = over_budget + over_time + over_return
    return (len(report.violations), severity, -len(route.stops))


async def route_validate(state: GraphState) -> dict:
    constraints = state["constraints"]
    assert constraints is not None

    valid: list[dict] = []
    reports: list[dict] = []
    evaluated: list[tuple[RoutePlan, ValidationReport]] = []

    for raw in state["candidate_routes"]:
        route = RoutePlan.model_validate(raw)
        report = _validate_route(route, constraints)
        evaluated.append((route, report))
        reports.append(report.model_dump(mode="json"))
        if report.feasible:
            valid.append(route.model_dump(mode="json"))

    relaxed: list[str] = []
    degraded = False
    if not valid and evaluated and ("relax_attempt" not in state or int(state.get("relax_attempt", 0)) >= 1):
        best_route, best_report = min(
            evaluated,
            key=lambda item: _route_violation_rank(item[0], constraints, item[1]),
        )
        valid = [best_route.model_dump(mode="json")]
        relaxed.append("route_validate_degraded_best_effort")
        degraded = True
        if best_report.feasible:
            best_report.feasible = False

    update = phase_update(
        "route_validate",
        summary=f"valid={len(valid)} violations={sum(len(r.get('violations') or []) for r in reports)}",
        valid_routes=valid,
        validation_reports=reports,
        relaxed_constraints=relaxed,
        degraded=degraded,
    )
    update["phase_log"][0].update({
        "valid_count": len(valid),
        "violation_count": sum(len(r.get("violations") or []) for r in reports),
        "degraded": degraded,
    })
    return update
