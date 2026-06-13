"""[4] route_validate — 硬约束校验。"""

from ...models.route import RoutePlan, ValidationReport
from ..state import GraphState, phase_update


async def route_validate(state: GraphState) -> dict:
    constraints = state["constraints"]
    assert constraints is not None

    valid: list[dict] = []
    reports: list[dict] = []

    for raw in state["candidate_routes"]:
        route = RoutePlan.model_validate(raw)
        violations: list[str] = []

        if route.estimated_cost_per_person > constraints["budget_per_person"]:
            violations.append(
                f"人均 {route.estimated_cost_per_person} 超过预算 {constraints['budget_per_person']}"
            )

        time_budget = constraints.get("time_budget_minutes")
        if time_budget and route.total_duration_min > time_budget:
            violations.append(
                f"总时长 {route.total_duration_min} 分钟超过预算 {time_budget} 分钟"
            )

        report = ValidationReport(
            route_id=route.plan_id,
            feasible=len(violations) == 0,
            violations=violations,
        )
        reports.append(report.model_dump(mode="json"))
        if report.feasible:
            valid.append(route.model_dump(mode="json"))

    relaxed: list[str] = []
    if not valid and state["candidate_routes"]:
        relaxed.append("budget_or_time_relaxed")
        valid = list(state["candidate_routes"][:1])
        for report in reports:
            report["feasible"] = True

    return phase_update(
        "route_validate",
        valid_routes=valid,
        validation_reports=reports,
        relaxed_constraints=relaxed,
        degraded=bool(relaxed),
    )
