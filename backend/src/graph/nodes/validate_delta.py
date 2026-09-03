"""[Replan 5] validate_delta — 仅校验变更部分。"""

from ...models.route import RoutePlan, ValidationReport
from ...services.category_taxonomy import category_matches_request
from ...services.poi_hours import weekday_from_date
from ...services.route_judge import judge_route
from ..state import GraphState, phase_update


async def validate_delta(state: GraphState) -> dict:
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

    poi_hours = {
        str(poi.get("poi_id")): list(poi.get("opening_hours") or [])
        for poi in (state.get("candidate_pois") or []) + (state.get("replacement_candidates") or [])
    }
    reports: list[ValidationReport] = []
    feasible_routes: list[dict] = []
    operations = state.get("replan_operations") or [state.get("replan_operation") or {}]
    original_stops = (state.get("original_route") or {}).get("stops") or []
    proposal_strategies = {
        str(item.get("proposal_id") or ""): str(item.get("strategy") or "")
        for item in state.get("replan_proposals") or []
    }
    for raw in routes:
        route = RoutePlan.model_validate(raw)
        strategy = proposal_strategies.get(route.plan_id, "")
        is_add_substitution = strategy.startswith(("replace_stop_", "remove_"))
        locked_indices = (
            state.get("explicitly_locked_stop_indices") or []
            if is_add_substitution
            else state.get("locked_stop_indices") or []
        )
        judgement = judge_route(
            route,
            constraints,
            poi_hours=poi_hours,
            weekday=weekday_from_date(state.get("input_ts")),
            original_route=state.get("original_route"),
            locked_indices=locked_indices,
        )
        operation_violations: list[str] = []
        route_text = " ".join(f"{stop.poi_name} {stop.category}" for stop in route.stops)
        for item in operations:
            requested = str(item.get("new_cuisine") or "")
            target = str(item.get("target_category") or item.get("exclude_category") or "")
            request_satisfied = any(
                category_matches_request(stop.category, requested) or requested in stop.poi_name
                for stop in route.stops
            ) if requested else True
            if item.get("type") in {"add", "replace"} and not request_satisfied:
                operation_violations.append(f"本次修改未加入用户要求的 {requested}")
            if (
                item.get("type") == "add"
                and len(route.stops) < len(original_stops) + 1
                and not is_add_substitution
            ):
                operation_violations.append("新增操作没有增加路线站点")
            if item.get("type") == "replace" and len(route.stops) != len(original_stops):
                operation_violations.append("替换操作改变了路线站点数量")
            if item.get("type") == "delete" and len(route.stops) >= len(original_stops):
                operation_violations.append("删除操作没有减少路线站点")
            if item.get("type") == "delete" and target and target in route_text:
                operation_violations.append(f"本次修改未移除用户排除的 {target}")
        violations_for_report = list(dict.fromkeys(judgement.hard_violations + operation_violations))
        reports.append(ValidationReport(
            route_id=route.plan_id,
            feasible=not violations_for_report,
            violations=violations_for_report,
            risks=judgement.risks,
            optimistic_duration_min=judgement.optimistic_duration_min,
            expected_duration_min=judgement.expected_duration_min,
            conservative_duration_min=judgement.conservative_duration_min,
        ))
        if not violations_for_report:
            feasible_routes.append(route.model_dump(mode="json"))

    delta_valid = bool(feasible_routes)
    violations = [item for report in reports for item in report.violations]
    return phase_update(
        "validate_delta",
        summary=f"valid={delta_valid} violations={len(violations)} retry={retry_count}",
        delta_valid=delta_valid,
        delta_retry_count=retry_count,
        validation_reports=[report.model_dump(mode="json") for report in reports],
        valid_routes=feasible_routes[:1],
        pending_change=None if delta_valid else {
            "operations": state.get("replan_operations") or [state.get("replan_operation") or {}],
            "status": "not_applied",
            "reasons": list(dict.fromkeys(violations))[:5],
        },
        planning_outcome="change_applied" if delta_valid else "change_rejected",
        degraded=not delta_valid,
    )
