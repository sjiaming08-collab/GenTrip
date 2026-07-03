"""Run natural-language route planning eval cases against the full GenTrip loop.

Usage:
    python scripts/evaluate_route_plans.py
    python scripts/evaluate_route_plans.py --json-output .runtime_logs/route_eval.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DEFAULT_CASES = BACKEND / "fixtures" / "route_eval_cases.json"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from src.services.plan_service import PlanService  # noqa: E402

DINING_CATEGORIES = {"本帮菜", "火锅", "小吃快餐", "西餐", "日料", "咖啡", "甜品", "酒吧", "川菜", "粤菜", "烧烤"}
SHOPPING_CATEGORIES = {"购物", "商场", "百货"}
MAX_REASONABLE_TRAVEL_MIN = 90


def parse_hhmm(value: object) -> int | None:
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


def load_cases(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("route eval cases must be a JSON list")
    return data


def top_route(state: dict[str, Any]) -> dict[str, Any] | None:
    results = state.get("route_results") or []
    if results:
        return results[0].get("route")
    valid = state.get("valid_routes") or []
    return valid[0] if valid else None


def route_source(state: dict[str, Any]) -> str | None:
    results = state.get("route_results") or []
    if not results:
        return None
    return results[0].get("source")


def top_route_planner_score(state: dict[str, Any]) -> float | None:
    results = state.get("route_results") or []
    if not results:
        return None
    scores = results[0].get("scores") or {}
    value = scores.get("final")
    return float(value) if value is not None else None


def validation_report_for(state: dict[str, Any], route: dict[str, Any] | None) -> dict[str, Any] | None:
    if not route:
        return None
    route_id = route.get("plan_id")
    for report in state.get("validation_reports") or []:
        if report.get("route_id") == route_id:
            return report
    return None


def candidate_domain_index(state: dict[str, Any]) -> dict[str, str]:
    index: dict[str, str] = {}
    for poi in state.get("candidate_pois") or []:
        poi_id = poi.get("poi_id")
        dimension = poi.get("dimension")
        if poi_id and dimension:
            index[poi_id] = dimension
    return index


def category_domain(category: str) -> str:
    if category in DINING_CATEGORIES:
        return "dining"
    if category in SHOPPING_CATEGORIES:
        return "shopping"
    return "sightseeing"


def route_domains(route: dict[str, Any], state: dict[str, Any]) -> set[str]:
    by_poi = candidate_domain_index(state)
    domains: set[str] = set()
    for stop in route.get("stops") or []:
        domain = by_poi.get(stop.get("poi_id"))
        if domain:
            domains.add(domain)
        else:
            domains.add(category_domain(str(stop.get("category") or "")))
    return domains


def route_categories(route: dict[str, Any]) -> set[str]:
    return {str(stop.get("category") or "") for stop in route.get("stops") or []}


def independent_legal_violations(state: dict[str, Any], route: dict[str, Any] | None) -> list[str]:
    if not route:
        return ["no_route"]

    constraints = state.get("constraints") or {}
    violations: list[str] = []

    budget = constraints.get("budget_per_person")
    cost = route.get("estimated_cost_per_person")
    if budget is not None and cost is not None and int(cost) > int(budget):
        violations.append(f"cost_over_budget:{cost}>{budget}")

    time_budget = constraints.get("time_budget_minutes")
    duration = route.get("total_duration_min")
    if time_budget is not None and duration is not None and int(duration) > int(time_budget):
        violations.append(f"duration_over_budget:{duration}>{time_budget}")

    return_by = parse_hhmm(constraints.get("return_by"))
    stops = route.get("stops") or []
    if return_by is not None and stops:
        end = parse_hhmm(stops[-1].get("departure_time"))
        if end is not None and end > return_by:
            violations.append(f"return_by_missed:{stops[-1].get('departure_time')}>{constraints.get('return_by')}")

    previous_departure: int | None = None
    for stop in stops:
        sequence = stop.get("sequence")
        arrival = parse_hhmm(stop.get("arrival_time"))
        departure = parse_hhmm(stop.get("departure_time"))
        travel = int(stop.get("travel_time_from_prev_min") or 0)
        if arrival is None or departure is None:
            violations.append(f"bad_time_format:stop_{sequence}")
            continue
        if departure < arrival:
            violations.append(f"departure_before_arrival:stop_{sequence}")
        if travel < 0:
            violations.append(f"negative_travel:stop_{sequence}")
        if travel > MAX_REASONABLE_TRAVEL_MIN:
            violations.append(f"travel_too_long:stop_{sequence}:{travel}")
        if previous_departure is not None and arrival < previous_departure + travel:
            violations.append(f"timeline_overlap:stop_{sequence}")
        previous_departure = departure

    return violations


def coverage_score(case: dict[str, Any], state: dict[str, Any], route: dict[str, Any] | None) -> tuple[float, list[str]]:
    if not route:
        return 0.0, ["no_route_for_coverage"]

    expect = case.get("expect") or {}
    missing: list[str] = []
    checks = 0
    passed = 0

    domains = route_domains(route, state)
    for domain in expect.get("required_domains") or []:
        checks += 1
        if domain in domains:
            passed += 1
        else:
            missing.append(f"missing_domain:{domain}")

    categories = route_categories(route)
    for group in expect.get("required_category_groups") or []:
        checks += 1
        if any(category in categories for category in group):
            passed += 1
        else:
            missing.append(f"missing_category:{'|'.join(group)}")

    if checks == 0:
        return 1.0, []
    return passed / checks, missing


def stop_score(case: dict[str, Any], route: dict[str, Any] | None) -> tuple[float, list[str]]:
    if not route:
        return 0.0, ["no_route_for_stop_count"]
    expect = case.get("expect") or {}
    min_stops = int(expect.get("min_stops") or 1)
    actual = len(route.get("stops") or [])
    if actual >= min_stops:
        return 1.0, []
    return max(0.0, actual / max(min_stops, 1)), [f"too_few_stops:{actual}<{min_stops}"]


def budget_score(state: dict[str, Any], route: dict[str, Any] | None) -> float:
    if not route:
        return 0.0
    budget = (state.get("constraints") or {}).get("budget_per_person")
    cost = route.get("estimated_cost_per_person")
    if budget is None or cost is None:
        return 1.0
    budget = max(int(budget), 1)
    cost = int(cost)
    if cost <= budget:
        return 1.0
    return max(0.0, 1.0 - (cost - budget) / budget)


def time_score(state: dict[str, Any], route: dict[str, Any] | None) -> float:
    if not route:
        return 0.0
    constraints = state.get("constraints") or {}
    time_budget = constraints.get("time_budget_minutes")
    duration = route.get("total_duration_min")
    if time_budget is not None and duration is not None:
        time_budget = max(int(time_budget), 1)
        duration = int(duration)
        if duration <= time_budget:
            return 1.0
        return max(0.0, 1.0 - (duration - time_budget) / time_budget)

    return_by = parse_hhmm(constraints.get("return_by"))
    stops = route.get("stops") or []
    if return_by is not None and stops:
        end = parse_hhmm(stops[-1].get("departure_time"))
        return 1.0 if end is not None and end <= return_by else 0.0
    return 1.0


def relaxation_score(state: dict[str, Any]) -> float:
    if state.get("degraded") or route_source(state) == "DEGRADED":
        return 0.4
    relaxed = state.get("relaxed_constraints") or []
    return 1.0 if not relaxed else 0.75


def evaluate_case(case: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    route = top_route(state)
    report = validation_report_for(state, route)
    independent_violations = independent_legal_violations(state, route)
    validation_violations = [] if not report else list(report.get("violations") or [])
    validation_feasible = bool(report and report.get("feasible"))
    is_completed = state.get("run_status") == "completed"
    is_legal = is_completed and validation_feasible and not independent_violations and not state.get("degraded")

    coverage, coverage_issues = coverage_score(case, state, route)
    stop, stop_issues = stop_score(case, route)
    b_score = budget_score(state, route)
    t_score = time_score(state, route)
    r_score = relaxation_score(state)
    legal_score = 1.0 if is_legal else 0.0

    quality_score = round(
        0.35 * legal_score
        + 0.25 * coverage
        + 0.15 * stop
        + 0.10 * b_score
        + 0.10 * t_score
        + 0.05 * r_score,
        3,
    )

    issues = []
    if not is_completed:
        issues.append(f"run_status:{state.get('run_status')}")
    issues.extend(independent_violations)
    issues.extend(validation_violations)
    issues.extend(coverage_issues)
    issues.extend(stop_issues)

    expect = case.get("expect") or {}
    passed = True
    if expect.get("must_complete", True) and not is_completed:
        passed = False
    if expect.get("must_be_legal", True) and not is_legal:
        passed = False
    min_quality = float(expect.get("min_quality_score") or 0)
    if quality_score < min_quality:
        passed = False

    route_summary = None
    if route:
        route_summary = {
            "plan_id": route.get("plan_id"),
            "plan_name": route.get("plan_name"),
            "stop_count": len(route.get("stops") or []),
            "categories": sorted(route_categories(route)),
            "domains": sorted(route_domains(route, state)),
            "duration_min": route.get("total_duration_min"),
            "cost_per_person": route.get("estimated_cost_per_person"),
            "last_departure": (route.get("stops") or [{}])[-1].get("departure_time"),
            "planner_score": top_route_planner_score(state),
            "source": route_source(state),
        }

    return {
        "id": case.get("id"),
        "query": case.get("query"),
        "passed": passed,
        "is_completed": is_completed,
        "is_legal": is_legal,
        "quality_score": quality_score,
        "min_quality_score": min_quality,
        "subscores": {
            "legal": legal_score,
            "coverage": round(coverage, 3),
            "stop_count": round(stop, 3),
            "budget": round(b_score, 3),
            "time": round(t_score, 3),
            "relaxation": round(r_score, 3),
        },
        "issues": issues,
        "route": route_summary,
        "constraints": state.get("constraints"),
        "geo_scope": state.get("geo_scope"),
        "route_generation_meta": state.get("route_generation_meta"),
        "validation_report": report,
    }


async def run_case(service: PlanService, case: dict[str, Any]) -> dict[str, Any]:
    state = await service.run_plan(
        case["query"],
        user_lat=case.get("user_lat"),
        user_lng=case.get("user_lng"),
    )
    return evaluate_case(case, state)


async def run_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    service = PlanService()
    results: list[dict[str, Any]] = []
    for case in cases:
        results.append(await run_case(service, case))
    return results


def print_report(results: list[dict[str, Any]]) -> None:
    print("route plan eval")
    print("id | pass | legal | quality | stops | domains | issues")
    print("-" * 96)
    for item in results:
        route = item.get("route") or {}
        issues = "; ".join(item.get("issues") or []) or "-"
        domains = ",".join(route.get("domains") or []) or "-"
        stops = route.get("stop_count", "-")
        print(
            f"{item['id']} | {item['passed']} | {item['is_legal']} | "
            f"{item['quality_score']:.3f} | {stops} | {domains} | {issues}"
        )

    passed = sum(1 for item in results if item["passed"])
    print("-" * 96)
    print(f"passed {passed}/{len(results)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate full-loop route planning outputs.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES, help="JSON eval case file")
    parser.add_argument("--json-output", type=Path, help="Optional path to write detailed JSON results")
    parser.add_argument("--no-fail", action="store_true", help="Always exit 0 after printing results")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cases = load_cases(args.cases)
    results = asyncio.run(run_cases(cases))
    print_report(results)

    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        with args.json_output.open("w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
            f.write("\n")

    if args.no_fail:
        return 0
    return 0 if all(item["passed"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())