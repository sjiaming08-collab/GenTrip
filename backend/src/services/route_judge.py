"""Single route-feasibility authority for Plan, Replan, and cached routes."""

from __future__ import annotations

from typing import Any

from ..models.planning import RouteJudgement
from ..models.route import RoutePlan
from .poi_hours import is_open_during

MAX_REASONABLE_TRAVEL_MIN = 90


def parse_hhmm(value: object) -> int | None:
    if not isinstance(value, str) or ":" not in value:
        return None
    hour_text, minute_text = value.split(":", 1)
    if not (hour_text.isdigit() and minute_text.isdigit()):
        return None
    hour, minute = int(hour_text), int(minute_text)
    if hour < 0 or hour > 47 or minute < 0 or minute > 59:
        return None
    return hour * 60 + minute


def _duration_range(route: RoutePlan) -> tuple[int, int, int]:
    lower_saving = 0
    upper_extra = 0
    for stop in route.stops:
        expected = max(0, stop.travel_time_from_prev_min)
        lower = stop.travel_time_lower_bound_min or expected
        upper = stop.travel_time_upper_bound_min or expected
        lower_saving += max(0, expected - lower)
        upper_extra += max(0, upper - expected)
    expected = route.total_duration_min
    return max(0, expected - lower_saving), expected, expected + upper_extra


def _matches_exclusion(stop_name: str, category: str, exclusions: list[str]) -> str | None:
    haystack = f"{stop_name} {category}".lower()
    return next((item for item in exclusions if item and str(item).lower() in haystack), None)


def _locked_stop_violations(
    route: RoutePlan,
    original_route: dict[str, Any] | None,
    locked_indices: list[int] | None,
) -> list[str]:
    if not original_route or not locked_indices:
        return []
    original_stops = original_route.get("stops") or []
    route_ids = {stop.poi_id for stop in route.stops}
    violations: list[str] = []
    for index in locked_indices:
        if index >= len(original_stops):
            continue
        original_id = str(original_stops[index].get("poi_id") or "")
        if original_id and original_id not in route_ids:
            violations.append(f"已锁定站点 {original_stops[index].get('poi_name') or original_id} 被移除")
    return violations


def judge_route(
    route: RoutePlan,
    constraints: dict[str, Any],
    *,
    poi_hours: dict[str, list[dict]] | None = None,
    weekday: int | None = None,
    original_route: dict[str, Any] | None = None,
    locked_indices: list[int] | None = None,
) -> RouteJudgement:
    violations: list[str] = []
    risks: list[str] = []
    poi_hours = poi_hours or {}
    optimistic, expected, conservative = _duration_range(route)

    budget = int(constraints.get("budget_per_person") or 0)
    if budget and route.estimated_cost_per_person > budget:
        violations.append(f"人均 {route.estimated_cost_per_person} 超过预算 {budget}")

    time_budget = constraints.get("time_budget_minutes")
    if time_budget and expected > int(time_budget):
        violations.append(f"总时长 {expected} 分钟超过预算 {int(time_budget)} 分钟")
    elif time_budget and conservative > int(time_budget):
        risks.append(f"交通波动下可能需要 {conservative} 分钟，超过计划 {int(time_budget)} 分钟")

    return_by = parse_hhmm(constraints.get("return_by"))
    route_end = parse_hhmm(route.stops[-1].departure_time) if route.stops else None
    if return_by is not None and route_end is not None and route_end > return_by:
        violations.append(f"结束时间 {route.stops[-1].departure_time} 晚于返回时间 {constraints['return_by']}")
    elif return_by is not None and route_end is not None:
        uncertainty = conservative - expected
        if route_end + uncertainty > return_by:
            risks.append(f"交通波动下可能晚于返回时间 {constraints['return_by']}")

    start_at = parse_hhmm(constraints.get("start_at"))
    first_arrival = parse_hhmm(route.stops[0].arrival_time) if route.stops else None
    if start_at is not None and first_arrival is not None and first_arrival < start_at:
        violations.append(f"首站到达时间 {route.stops[0].arrival_time} 早于出发时间 {constraints['start_at']}")

    queue_tolerance = constraints.get("queue_tolerance_minutes")
    if queue_tolerance is not None:
        for stop in route.stops:
            if stop.queue_wait_min > int(queue_tolerance):
                violations.append(
                    f"第 {stop.sequence} 站预计排队 {stop.queue_wait_min} 分钟超过上限 {int(queue_tolerance)} 分钟"
                )

    exclusions = [str(item) for item in constraints.get("excluded_categories") or []]
    for stop in route.stops:
        matched = _matches_exclusion(stop.poi_name, stop.category, exclusions)
        if matched:
            violations.append(f"第 {stop.sequence} 站 {stop.poi_name} 命中排除项 {matched}")
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    previous_departure: int | None = None
    for stop in route.stops:
        if stop.poi_id in seen_ids:
            violations.append(f"POI {stop.poi_name} 重复出现")
        seen_ids.add(stop.poi_id)
        normalized_name = "".join(stop.poi_name.casefold().split())
        if normalized_name in seen_names:
            violations.append(f"POI {stop.poi_name} 重复出现")
        seen_names.add(normalized_name)
        arrival = parse_hhmm(stop.arrival_time)
        departure = parse_hhmm(stop.departure_time)
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

        slot_window = stop.slot_time_window or {}
        window_start = parse_hhmm(slot_window.get("start"))
        window_end = parse_hhmm(slot_window.get("end"))
        if window_start is not None and arrival < window_start:
            violations.append(f"第 {stop.sequence} 站早于槽位时间窗开始")
        if window_end is not None and departure > window_end:
            violations.append(f"第 {stop.sequence} 站晚于槽位时间窗结束")

        open_result = is_open_during(poi_hours.get(stop.poi_id), arrival, departure, weekday=weekday)
        if open_result is False:
            violations.append(
                f"第 {stop.sequence} 站 {stop.poi_name} 在 {stop.arrival_time}-{stop.departure_time} 未营业"
            )

    violations.extend(_locked_stop_violations(route, original_route, locked_indices))
    return RouteJudgement(
        route_id=route.plan_id,
        feasible=not violations,
        hard_violations=list(dict.fromkeys(violations)),
        risks=list(dict.fromkeys(risks)),
        optimistic_duration_min=optimistic,
        expected_duration_min=expected,
        conservative_duration_min=conservative,
        estimated_cost_per_person=route.estimated_cost_per_person,
    )
