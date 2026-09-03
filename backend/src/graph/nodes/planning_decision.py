"""Planner V2 pre-retrieval feasibility decision."""

from __future__ import annotations

from ...models.planning import DurationEstimate, PlanningDecision, PlanningOption
from ...services.route_judge import parse_hhmm
from ..state import GraphState, phase_update

_VISIT_RANGE = {
    "dining": (45, 75, 90),
    "sightseeing": (45, 60, 90),
    "shopping": (30, 50, 75),
}

_TRAVEL_RANGE_BY_SCOPE = {
    "business_area": (8, 15, 25),
    "radius": (8, 15, 25),
    "district": (10, 20, 35),
    "city": (20, 35, 60),
}


def _available_minutes(constraints: dict) -> int | None:
    values: list[int] = []
    if constraints.get("time_budget_minutes"):
        values.append(int(constraints["time_budget_minutes"]))
    start = parse_hhmm(constraints.get("start_at"))
    end = parse_hhmm(constraints.get("return_by"))
    if start is not None and end is not None and end >= start:
        values.append(end - start)
    return min(values) if values else None


def assess_planning_feasibility(state: GraphState) -> PlanningDecision:
    constraints = state.get("constraints") or {}
    domains = list(dict.fromkeys(str(item) for item in constraints.get("domains") or [])) or ["sightseeing"]
    if constraints.get("preferred_cuisines") and "dining" not in domains:
        domains.append("dining")

    missing: list[str] = []
    location_ready = bool(
        constraints.get("city")
        or constraints.get("district")
        or constraints.get("location_mentions")
        or state.get("geo_scope")
        or (state.get("user_lat") is not None and state.get("user_lng") is not None)
    )
    if not location_ready:
        missing.append("location")
    available = _available_minutes(constraints)
    if available is None:
        missing.append("duration")

    scope_type = str(
        (state.get("geo_scope") or {}).get("scope_type")
        or ("district" if constraints.get("district") else "city")
    )
    travel_low, travel_expected, travel_high = _TRAVEL_RANGE_BY_SCOPE.get(scope_type, _TRAVEL_RANGE_BY_SCOPE["district"])
    legs = max(0, len(domains) - 1)
    optimistic = sum(_VISIT_RANGE.get(domain, (30, 60, 90))[0] for domain in domains) + legs * travel_low
    expected_without_buffer = sum(_VISIT_RANGE.get(domain, (30, 60, 90))[1] for domain in domains) + legs * travel_expected
    conservative_without_buffer = sum(_VISIT_RANGE.get(domain, (30, 60, 90))[2] for domain in domains) + legs * travel_high
    buffer_minutes = max(10, round((available or expected_without_buffer) * 0.10))
    expected = expected_without_buffer + buffer_minutes
    conservative = conservative_without_buffer + max(buffer_minutes, 15)
    estimate = DurationEstimate(
        optimistic_minutes=optimistic,
        expected_minutes=expected,
        conservative_minutes=conservative,
        available_minutes=available,
        buffer_minutes=buffer_minutes,
        confidence="low" if not state.get("geo_scope") else "medium",
    )

    if missing:
        return PlanningDecision(
            status="clarification_required",
            outcome="clarification_required",
            estimate=estimate,
            reasons=[f"缺少关键规划信息：{'、'.join(missing)}"],
            options=[PlanningOption(action="provide_constraints", label="补充地点或可用时间")],
        )
    assert available is not None
    if optimistic > available:
        shortfall = optimistic - available
        return PlanningDecision(
            status="infeasible",
            outcome="infeasible",
            estimate=estimate,
            reasons=[f"即使按最短停留和交通下界估算，仍超出可用时间 {shortfall} 分钟"],
            options=[
                PlanningOption(action="extend_time", label=f"至少延长 {shortfall + 15} 分钟"),
                PlanningOption(action="reduce_activity", label="减少一个必要活动"),
            ],
        )
    if expected > available or conservative > available:
        return PlanningDecision(
            status="marginal",
            outcome="marginal",
            estimate=estimate,
            reasons=["本地交通估算存在波动，将继续检索并用具体 POI 坐标复核"],
        )
    return PlanningDecision(status="ready", outcome="route_ready", estimate=estimate)


async def planning_decision(state: GraphState) -> dict:
    decision = assess_planning_feasibility(state)
    estimate = decision.estimate
    update = phase_update(
        "planning_decision",
        summary=(
            f"status={decision.status} optimistic={estimate.optimistic_minutes} "
            f"expected={estimate.expected_minutes} conservative={estimate.conservative_minutes} "
            f"available={estimate.available_minutes}"
        ),
        planning_decision=decision.model_dump(mode="json"),
        planning_outcome=decision.outcome,
    )
    update["phase_log"][0].update({
        "decision_status": decision.status,
        "duration_estimate": estimate.model_dump(mode="json"),
    })
    return update
