"""Declarative runner for deterministic multi-turn planning golden cases."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.runtime.store import MemoryRuntimeStore
from src.services.plan_service import PlanService, infer_reply_type


GOLDEN_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "golden_conversations.json"


def load_golden_cases() -> list[dict[str, Any]]:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def _route(state: dict[str, Any]) -> dict[str, Any]:
    result = (state.get("route_results") or [{}])[0]
    return result.get("route") or {}


def _categories(state: dict[str, Any]) -> list[str]:
    return [str(stop.get("category")) for stop in _route(state).get("stops") or []]


def _minute(value: object) -> int | None:
    if not isinstance(value, str) or ":" not in value:
        return None
    hour, minute = value.split(":", 1)
    if not (hour.isdigit() and minute.isdigit()):
        return None
    return int(hour) * 60 + int(minute)


def route_quality(state: dict[str, Any], expect: dict[str, Any] | None = None) -> dict[str, float | int | bool]:
    """Return deterministic, explainable route-quality signals for golden tests."""
    route = _route(state)
    stops = route.get("stops") or []
    constraints = state.get("constraints") or {}
    ratings = {
        str(poi.get("poi_id")): float(poi.get("rating") or 4.0)
        for poi in state.get("candidate_pois") or []
        if poi.get("poi_id")
    }
    stop_ratings = [ratings.get(str(stop.get("poi_id")), 4.0) for stop in stops]
    total_travel = sum(max(0, int(stop.get("travel_time_from_prev_min") or 0)) for stop in stops)
    max_leg_travel = max((int(stop.get("travel_time_from_prev_min") or 0) for stop in stops), default=0)
    max_queue_wait = max((int(stop.get("queue_wait_min") or 0) for stop in stops), default=0)
    unique_pois = len({str(stop.get("poi_id")) for stop in stops}) == len(stops)
    category_diversity = len(set(_categories(state))) / len(stops) if stops else 1.0

    temporal_feasible = True
    previous_departure: int | None = None
    for stop in stops:
        arrival = _minute(stop.get("arrival_time"))
        departure = _minute(stop.get("departure_time"))
        if arrival is None or departure is None or departure < arrival:
            temporal_feasible = False
            break
        if previous_departure is not None and arrival < previous_departure + int(stop.get("travel_time_from_prev_min") or 0):
            temporal_feasible = False
            break
        previous_departure = departure

    within_budget = route.get("estimated_cost_per_person", 0) <= int(constraints.get("budget_per_person") or 0)
    within_duration = not constraints.get("time_budget_minutes") or route.get("total_duration_min", 0) <= int(constraints["time_budget_minutes"])
    return_by = _minute(constraints.get("return_by"))
    route_end = _minute(stops[-1].get("departure_time")) if stops else None
    within_return_by = return_by is None or route_end is None or route_end <= return_by
    return_slack_min = return_by - route_end if return_by is not None and route_end is not None else None
    start_at = _minute(constraints.get("start_at"))
    first_arrival = _minute(stops[0].get("arrival_time")) if stops else None
    within_start_at = start_at is None or first_arrival is None or first_arrival >= start_at
    start_slack_min = first_arrival - start_at if start_at is not None and first_arrival is not None else None
    queue_tolerance = constraints.get("queue_tolerance_minutes")
    within_queue = queue_tolerance is None or max_queue_wait <= int(queue_tolerance)
    feasible = all((temporal_feasible, within_budget, within_duration, within_return_by, within_start_at, within_queue))
    budget = int(constraints.get("budget_per_person") or 0)
    budget_utilization = route.get("estimated_cost_per_person", 0) / budget if budget else 0.0

    expected_categories = set((expect or {}).get("required_categories") or [])
    actual_categories = set(_categories(state))
    preference_coverage = (
        len(expected_categories & actual_categories) / len(expected_categories)
        if expected_categories else 1.0
    )
    forbidden_categories = set((expect or {}).get("forbidden_categories") or [])
    exclusion_compliance = not bool(forbidden_categories & actual_categories)

    avg_rating = sum(stop_ratings) / len(stop_ratings) if stop_ratings else 0.0
    # A short walking route, high quality POIs, category variety and no duplicated POIs
    # receive credit only after all explicit constraints are satisfied.
    score = (
        (35.0 if feasible else 0.0)
        + min(avg_rating / 5.0, 1.0) * 25.0
        + max(0.0, 1.0 - total_travel / 120.0) * 20.0
        + category_diversity * 10.0
        + (10.0 if unique_pois else 0.0)
    )
    constraint_score = (
        (60.0 if feasible else 0.0)
        + preference_coverage * 25.0
        + (10.0 if exclusion_compliance else 0.0)
        + (5.0 if unique_pois else 0.0)
    )
    expectation_score = 0.7 * constraint_score + 0.3 * score
    return {
        "score": round(score, 1),
        "feasible": feasible,
        "avg_rating": round(avg_rating, 2),
        "total_travel_min": total_travel,
        "max_leg_travel_min": max_leg_travel,
        "max_queue_wait_min": max_queue_wait,
        "return_slack_min": return_slack_min,
        "start_slack_min": start_slack_min,
        "budget_utilization": round(budget_utilization, 2),
        "category_diversity": round(category_diversity, 2),
        "unique_pois": unique_pois,
        "preference_coverage": round(preference_coverage, 2),
        "exclusion_compliance": exclusion_compliance,
        "constraint_score": round(constraint_score, 1),
        "expectation_score": round(expectation_score, 1),
    }


def assert_turn(state: dict[str, Any], expect: dict[str, Any]) -> None:
    assert state.get("run_status") == "completed"
    for field in ("turn_mode", "plan_path", "planning_outcome"):
        if field in expect:
            assert state.get(field) == expect[field]
    if "reply_type" in expect:
        assert infer_reply_type(state) == expect["reply_type"]

    constraints = state.get("constraints") or {}
    for key, value in (expect.get("constraints") or {}).items():
        assert constraints.get(key) == value

    route = _route(state)
    stops = route.get("stops") or []
    if "min_stops" in expect:
        assert len(stops) >= int(expect["min_stops"])
    if "stop_count" in expect:
        assert len(stops) == int(expect["stop_count"])
    if "max_route_cost" in expect:
        assert route.get("estimated_cost_per_person", 0) <= int(expect["max_route_cost"])

    categories = _categories(state)
    for category in expect.get("required_categories") or []:
        assert category in categories
    for category in expect.get("forbidden_categories") or []:
        assert category not in categories

    expected_changes = set(expect.get("diff_change_types") or [])
    if expected_changes:
        changes = (state.get("diff_result") or {}).get("changes") or []
        actual_changes = {item.get("type") for item in changes}
        assert expected_changes <= actual_changes

    quality_expect = expect.get("quality") or {}
    if quality_expect:
        quality = route_quality(state, expect)
        assert quality["feasible"], quality
        for key, metric, operator in (
            ("min_score", "score", lambda actual, expected: actual >= expected),
            ("min_avg_rating", "avg_rating", lambda actual, expected: actual >= expected),
            ("max_total_travel_min", "total_travel_min", lambda actual, expected: actual <= expected),
            ("max_leg_travel_min", "max_leg_travel_min", lambda actual, expected: actual <= expected),
            ("max_queue_wait_min", "max_queue_wait_min", lambda actual, expected: actual <= expected),
            ("min_category_diversity", "category_diversity", lambda actual, expected: actual >= expected),
            ("min_preference_coverage", "preference_coverage", lambda actual, expected: actual >= expected),
            ("min_constraint_score", "constraint_score", lambda actual, expected: actual >= expected),
            ("min_expectation_score", "expectation_score", lambda actual, expected: actual >= expected),
            ("min_return_slack_min", "return_slack_min", lambda actual, expected: actual is not None and actual >= expected),
            ("max_start_slack_min", "start_slack_min", lambda actual, expected: actual is not None and actual <= expected),
            ("min_budget_utilization", "budget_utilization", lambda actual, expected: actual >= expected),
            ("max_budget_utilization", "budget_utilization", lambda actual, expected: actual <= expected),
        ):
            if key in quality_expect:
                assert operator(quality[metric], quality_expect[key]), quality
        if quality_expect.get("require_unique_pois"):
            assert quality["unique_pois"], quality
        if quality_expect.get("require_exclusion_compliance"):
            assert quality["exclusion_compliance"], quality


async def run_case(case: dict[str, Any]) -> list[dict[str, Any]]:
    service = PlanService(store=MemoryRuntimeStore())
    session_id = f"golden-{case['id']}"
    states: list[dict[str, Any]] = []
    for turn in case["turns"]:
        if turn.get("action") == "cancel_run":
            initial, _session = await service._prepare_run(turn["query"], session_id=session_id)
            assert await service.cancel_run(initial["run_id"])
            run = await service.get_run(initial["run_id"])
            assert run is not None
            state = {"run_id": initial["run_id"], "run_status": run["status"]}
            assert state["run_status"] == turn["expect"]["run_status"]
            states.append(state)
            continue
        initial, session = await service._prepare_run(turn["query"], session_id=session_id)
        initial["input_ts"] = "2026-08-18T03:00:00+00:00"
        state = await service._execute_run(initial, session)
        assert_turn(state, turn["expect"])
        states.append(state)
    return states
