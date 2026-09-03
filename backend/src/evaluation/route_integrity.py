"""Deterministic integrity metrics for blueprint-generated routes."""

from __future__ import annotations

from typing import Any

from ..services.route_judge import parse_hhmm


def route_integrity_metrics(state: dict[str, Any], route: dict[str, Any] | None) -> dict[str, Any]:
    if not route:
        return {
            "route_leg_complete": False,
            "fabricated_poi_count": 0,
            "meal_window_satisfaction_rate": 0.0,
            "explicit_anchor_satisfied": False,
            "hard_constraint_violation_count": 0,
        }

    stops = list(route.get("stops") or [])
    legs = list(route.get("legs") or [])
    leg_complete = len(legs) == max(0, len(stops) - 1) and all(
        leg.get("from_poi_id") == stops[index].get("poi_id")
        and leg.get("to_poi_id") == stops[index + 1].get("poi_id")
        and leg.get("mode")
        and leg.get("source")
        and leg.get("confidence")
        for index, leg in enumerate(legs)
        if index + 1 < len(stops)
    )

    provider_ids = {
        str(item.get("poi_id"))
        for item in state.get("candidate_pois") or []
        if item.get("poi_id")
    }
    fabricated = (
        sum(str(stop.get("poi_id")) not in provider_ids for stop in stops)
        if provider_ids and route.get("blueprint_id")
        else 0
    )

    meal_stops = [stop for stop in stops if stop.get("slot_role") == "meal"]
    meal_satisfied = 0
    for stop in meal_stops:
        window = stop.get("slot_time_window") or {}
        arrival = parse_hhmm(stop.get("arrival_time"))
        departure = parse_hhmm(stop.get("departure_time"))
        start = parse_hhmm(window.get("start"))
        end = parse_hhmm(window.get("end"))
        if (
            arrival is not None
            and departure is not None
            and (start is None or arrival >= start)
            and (end is None or departure <= end)
        ):
            meal_satisfied += 1

    constraints = state.get("constraints") or {}
    anchor_target = constraints.get("anchor_count_explicit")
    anchor_count = sum(stop.get("slot_role") == "anchor" for stop in stops)
    explicit_anchor_satisfied = (
        True if not anchor_target else anchor_count == int(anchor_target)
    )
    violations = [
        violation
        for report in state.get("validation_reports") or []
        if report.get("route_id") == route.get("plan_id")
        for violation in report.get("violations") or []
    ]
    return {
        "route_leg_complete": leg_complete,
        "fabricated_poi_count": fabricated,
        "meal_window_satisfaction_rate": (
            round(meal_satisfied / len(meal_stops), 3) if meal_stops else 1.0
        ),
        "explicit_anchor_satisfied": explicit_anchor_satisfied,
        "hard_constraint_violation_count": len(violations),
    }
