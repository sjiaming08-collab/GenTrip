"""Run GenTrip LocalLifeBench through the full planning and replan graphs."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DEFAULT_DATASET = BACKEND / "fixtures" / "local_life_benchmark.json"
DEFAULT_POIS = BACKEND / "fixtures" / "pois.json"
FIXED_INPUT_TS = "2026-08-18T03:00:00+00:00"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from evaluate_route_plans import (  # noqa: E402
    evaluate_case,
    independent_legal_violations,
    route_categories,
    top_route,
)
from src.config import settings  # noqa: E402
from src.evaluation import RouteJudge  # noqa: E402
from src.graph.state import token_usage_from_calls  # noqa: E402
from src.runtime.events import RuntimeEventBus  # noqa: E402
from src.runtime.store import MemoryRuntimeStore  # noqa: E402
from src.services.plan_service import PlanService  # noqa: E402
from src.services.poi_retrieval import use_poi_fixture  # noqa: E402
from src.services.route_bundle_cache import route_bundle_cache  # noqa: E402


def load_dataset(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data.get("metadata"):
        raise ValueError("local-life dataset must be a versioned JSON object")
    if not data.get("cases") or not data.get("conversations"):
        raise ValueError("local-life dataset must contain cases and conversations")
    return data


def constraint_check(case: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    expected = (case.get("expect") or {}).get("expected_constraints") or {}
    actual = state.get("constraints") or {}
    checks: list[dict[str, Any]] = []
    for field in (
        "district",
        "time_budget_minutes",
        "start_at",
        "return_by",
        "queue_tolerance_minutes",
        "budget_per_person",
        "poi_count",
    ):
        if field in expected:
            checks.append({
                "field": field,
                "expected": expected[field],
                "actual": actual.get(field),
                "passed": actual.get(field) == expected[field],
            })
    for field in ("domains", "excluded_categories"):
        if field in expected:
            expected_values = set(expected.get(field) or [])
            actual_values = set(actual.get(field) or [])
            checks.append({
                "field": field,
                "expected": sorted(expected_values),
                "actual": sorted(actual_values),
                "passed": expected_values.issubset(actual_values),
            })
    return {
        "passed": all(item["passed"] for item in checks),
        "score": round(sum(item["passed"] for item in checks) / max(len(checks), 1), 3),
        "checks": checks,
    }


def _operation_types(state: dict[str, Any]) -> list[str]:
    operations = state.get("replan_operations") or []
    if not operations and state.get("replan_operation"):
        operations = [state["replan_operation"]]
    if not operations:
        operations = (state.get("turn_plan") or {}).get("operations") or []
    return [str(item.get("type")) for item in operations if item.get("type")]


async def run_plan_at_fixed_time(
    service: PlanService,
    query: str,
    *,
    session_id: str,
) -> dict[str, Any]:
    initial, session = await service._prepare_run(query, session_id=session_id)
    initial["input_ts"] = FIXED_INPUT_TS
    return await service._execute_run(initial, session)


def evaluate_conversation_turn(
    turn: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    expect = turn.get("expect") or {}
    route = top_route(state)
    categories = route_categories(route) if route else set()
    issues: list[str] = []
    if state.get("run_status") != "completed":
        issues.append(f"run_status:{state.get('run_status')}")
    if expect.get("turn_mode") and state.get("turn_mode") != expect["turn_mode"]:
        issues.append(f"turn_mode:{state.get('turn_mode')}!={expect['turn_mode']}")
    if expect.get("operation") and expect["operation"] not in _operation_types(state):
        issues.append(f"missing_operation:{expect['operation']}")
    for group in expect.get("required_category_groups") or []:
        if not categories.intersection(str(item) for item in group):
            issues.append(f"missing_category_group:{'|'.join(group)}")
    stop_count = len((route or {}).get("stops") or [])
    if stop_count < int(expect.get("min_stops") or 0):
        issues.append(f"too_few_stops:{stop_count}<{expect['min_stops']}")
    issues.extend(independent_legal_violations(state, route))
    return {
        "query": turn["query"],
        "passed": not issues,
        "turn_mode": state.get("turn_mode"),
        "operations": _operation_types(state),
        "categories": sorted(categories),
        "stop_count": stop_count,
        "issues": issues,
        "runtime": {
            "token_usage": token_usage_from_calls(state.get("llm_calls") or []),
            "phase_count": len(state.get("phase_log") or []),
        },
        "diagnostics": {
            "replacement_categories": dict(Counter(
                str(item.get("category") or "")
                for item in state.get("replacement_candidates") or []
            )),
            "replacement_candidates": [
                {
                    "name": item.get("name"),
                    "category": item.get("category"),
                    "district": item.get("district"),
                }
                for item in state.get("replacement_candidates") or []
            ],
            "proposal_categories": [
                sorted(route_categories(route))
                for route in state.get("candidate_routes") or []
            ],
            "validation_violations": [
                item.get("violations") for item in state.get("validation_reports") or []
            ],
            "route_diff": state.get("route_diff"),
            "phase_summaries": [
                f"{item.get('phase')}:{item.get('summary')}"
                for item in state.get("phase_log") or []
            ],
        },
    }


async def run_single_cases(
    cases: list[dict[str, Any]], service: PlanService, *, quiet: bool = False
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        started = perf_counter()
        state = await run_plan_at_fixed_time(
            service,
            case["query"],
            session_id=f"llb-single-{case['id']}",
        )
        route_result = evaluate_case(case, state)
        constraints = constraint_check(case, state)
        route_result.update({
            "agent_id": case["agent_id"],
            "difficulty": case["difficulty"],
            "split": case["split"],
            "constraint_check": constraints,
            "end_to_end_passed": bool(route_result["passed"] and constraints["passed"]),
            "runtime": {
                "latency_ms": round((perf_counter() - started) * 1000, 1),
                "token_usage": token_usage_from_calls(state.get("llm_calls") or []),
                "phase_count": len(state.get("phase_log") or []),
            },
            "diagnostics": {
                "candidate_categories": dict(Counter(
                    str(item.get("category") or "") for item in state.get("candidate_pois") or []
                )),
                "candidate_districts": dict(Counter(
                    str(item.get("district") or "") for item in state.get("candidate_pois") or []
                )),
                "candidate_domains": dict(Counter(
                    str(item.get("dimension") or "") for item in state.get("candidate_pois") or []
                )),
                "retrieval_meta": state.get("retrieval_meta"),
                "route_generation_meta": state.get("route_generation_meta"),
                "generated_routes": [
                    {
                        "stop_count": len(route.get("stops") or []),
                        "categories": [stop.get("category") for stop in route.get("stops") or []],
                        "times": [
                            f"{stop.get('arrival_time')}-{stop.get('departure_time')}"
                            for stop in route.get("stops") or []
                        ],
                        "duration_min": route.get("total_duration_min"),
                        "cost_per_person": route.get("estimated_cost_per_person"),
                    }
                    for route in state.get("candidate_routes") or []
                ],
                "validation_reports": state.get("validation_reports") or [],
                "phase_summaries": [
                    f"{item.get('phase')}:{item.get('summary')}"
                    for item in state.get("phase_log") or []
                ],
            },
        })
        results.append(route_result)
        if not quiet:
            print(
                f"[single {index}/{len(cases)}] {case['id']} "
                f"constraint={constraints['passed']} route={route_result['passed']} "
                f"quality={route_result['quality_score']:.3f}"
            )
    return results


async def run_conversations(
    conversations: list[dict[str, Any]], service: PlanService, *, quiet: bool = False
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for index, conversation in enumerate(conversations, start=1):
        turns: list[dict[str, Any]] = []
        session_id = f"llb-multi-{conversation['id']}"
        for turn in conversation["turns"]:
            started = perf_counter()
            state = await run_plan_at_fixed_time(service, turn["query"], session_id=session_id)
            result = evaluate_conversation_turn(turn, state)
            result["runtime"]["latency_ms"] = round((perf_counter() - started) * 1000, 1)
            turns.append(result)
        item = {
            "id": conversation["id"],
            "agent_id": conversation["agent_id"],
            "split": conversation["split"],
            "passed": all(turn["passed"] for turn in turns),
            "turns": turns,
        }
        results.append(item)
        if not quiet:
            print(
                f"[multi {index}/{len(conversations)}] {conversation['id']} "
                f"passed={item['passed']} turns={sum(turn['passed'] for turn in turns)}/{len(turns)}"
            )
    return results


def _rate(items: list[dict[str, Any]], key: str) -> float:
    return round(sum(bool(item.get(key)) for item in items) / max(len(items), 1), 3)


def _group_rates(cases: list[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        grouped[str(case.get(field))].append(case)
    return {
        key: {
            "case_count": len(items),
            "end_to_end_pass_rate": _rate(items, "end_to_end_passed"),
            "constraint_pass_rate": round(
                sum(bool(item.get("constraint_check", {}).get("passed")) for item in items)
                / max(len(items), 1),
                3,
            ),
            "route_pass_rate": _rate(items, "passed"),
            "mean_quality_score": round(mean(item["quality_score"] for item in items), 3),
        }
        for key, items in sorted(grouped.items())
    }


def build_report(
    dataset: dict[str, Any],
    cases: list[dict[str, Any]],
    conversations: list[dict[str, Any]],
    *,
    live_llm: bool,
) -> dict[str, Any]:
    constraint_passes = sum(item["constraint_check"]["passed"] for item in cases)
    route_passes = sum(item["passed"] for item in cases)
    e2e_passes = sum(item["end_to_end_passed"] for item in cases)
    conversation_turns = [turn for item in conversations for turn in item["turns"]]
    total_tokens = sum(
        int(item["runtime"]["token_usage"].get("total_tokens") or 0) for item in cases
    ) + sum(
        int(turn["runtime"]["token_usage"].get("total_tokens") or 0)
        for turn in conversation_turns
    )
    report = {
        "benchmark": dataset["metadata"],
        "execution": {
            "live_llm": live_llm,
            "official_travelplanner_score": None,
            "evaluation_note": "GenTrip-native benchmark inspired by TravelPlanner evaluation principles",
        },
        "summary": {
            "single_case_count": len(cases),
            "constraint_pass_rate": round(constraint_passes / max(len(cases), 1), 3),
            "route_pass_rate": round(route_passes / max(len(cases), 1), 3),
            "single_end_to_end_pass_rate": round(e2e_passes / max(len(cases), 1), 3),
            "mean_quality_score": round(mean(item["quality_score"] for item in cases), 3) if cases else 0.0,
            "conversation_count": len(conversations),
            "conversation_pass_rate": _rate(conversations, "passed"),
            "conversation_turn_count": len(conversation_turns),
            "conversation_turn_pass_rate": _rate(conversation_turns, "passed"),
            "total_tokens": total_tokens,
        },
        "by_agent": _group_rates(cases, "agent_id"),
        "by_difficulty": _group_rates(cases, "difficulty"),
        "by_split": _group_rates(cases, "split"),
        "cases": cases,
        "conversations": conversations,
    }
    report["quality_gate"] = evaluate_quality_gate(report)
    return report


def evaluate_quality_gate(report: dict[str, Any]) -> dict[str, Any]:
    metadata = report.get("benchmark") or {}
    thresholds = metadata.get("quality_gate") or {}
    summary = report.get("summary") or {}
    checks: list[dict[str, Any]] = []

    def add_check(metric: str, threshold_key: str) -> None:
        actual = float(summary.get(metric) or 0.0)
        minimum = float(thresholds.get(threshold_key) or 0.0)
        checks.append({
            "metric": metric,
            "actual": actual,
            "minimum": minimum,
            "passed": actual >= minimum,
        })

    if int(summary.get("single_case_count") or 0) > 0:
        add_check("constraint_pass_rate", "minimum_constraint_pass_rate")
        add_check(
            "single_end_to_end_pass_rate",
            "minimum_single_end_to_end_pass_rate",
        )
        add_check("mean_quality_score", "minimum_mean_quality_score")
    if int(summary.get("conversation_turn_count") or 0) > 0:
        add_check(
            "conversation_turn_pass_rate",
            "minimum_conversation_turn_pass_rate",
        )
    if not checks:
        checks.append({
            "metric": "non_empty_evaluation",
            "actual": 0.0,
            "minimum": 1.0,
            "passed": False,
        })
    return {
        "passed": all(item["passed"] for item in checks),
        "checks": checks,
    }


async def add_judgements(report: dict[str, Any], source_cases: list[dict[str, Any]]) -> None:
    by_id = {item["id"]: item for item in source_cases}
    judge = RouteJudge()
    passed = 0
    for item in report["cases"]:
        verdict = await judge.evaluate(by_id[item["id"]], item)
        payload = verdict.model_dump(mode="json")
        payload["normalized_score"] = verdict.normalized_score
        item["llm_judge"] = payload
        passed += verdict.verdict == "pass"
    report["summary"]["llm_judge_pass_rate"] = round(passed / max(len(report["cases"]), 1), 3)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate GenTrip LocalLifeBench")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--poi-fixture", type=Path, default=DEFAULT_POIS)
    parser.add_argument("--agent-id", action="append")
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--split", choices=("development", "validation", "test"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--single-only", action="store_true")
    parser.add_argument("--conversations-only", action="store_true")
    parser.add_argument("--live-llm", action="store_true")
    parser.add_argument("--llm-judge", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument(
        "--enforce-gate",
        action="store_true",
        help="Exit non-zero when the LocalLifeBench quality gate fails",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=ROOT / ".runtime_logs" / "local-life-eval.json",
    )
    return parser.parse_args()


async def async_main(args: argparse.Namespace) -> dict[str, Any]:
    if args.single_only and args.conversations_only:
        raise ValueError("--single-only and --conversations-only are mutually exclusive")
    if args.live_llm and not settings.llm_api_key:
        raise RuntimeError("--live-llm requires a configured LLM API key")
    dataset = load_dataset(args.dataset)
    cases = list(dataset["cases"])
    conversations = list(dataset["conversations"])
    if args.agent_id:
        requested = set(args.agent_id)
        cases = [item for item in cases if item["agent_id"] in requested]
        conversations = [item for item in conversations if item["agent_id"] in requested]
    if args.case_id:
        requested_cases = set(args.case_id)
        cases = [item for item in cases if item["id"] in requested_cases]
    if args.split:
        cases = [item for item in cases if item["split"] == args.split]
        conversations = [item for item in conversations if item["split"] == args.split]
    if args.limit:
        cases = cases[: args.limit]
    if args.conversations_only:
        cases = []
    if args.single_only:
        conversations = []

    service = PlanService(store=MemoryRuntimeStore(), event_bus=RuntimeEventBus(""))
    original_llm_enabled = settings.llm_enabled
    original_redis_url = settings.redis_url
    settings.llm_enabled = bool(args.live_llm)
    settings.redis_url = ""
    route_bundle_cache.clear()
    try:
        with use_poi_fixture(args.poi_fixture):
            case_results = await run_single_cases(cases, service, quiet=args.quiet)
            conversation_results = await run_conversations(
                conversations, service, quiet=args.quiet
            )
        report = build_report(
            dataset,
            case_results,
            conversation_results,
            live_llm=args.live_llm,
        )
        if args.llm_judge:
            if not settings.llm_api_key:
                raise RuntimeError("--llm-judge requires a configured LLM API key")
            await add_judgements(report, cases)
        return report
    finally:
        settings.llm_enabled = original_llm_enabled
        settings.redis_url = original_redis_url
        route_bundle_cache.clear()


def main() -> int:
    args = parse_args()
    report = asyncio.run(async_main(args))
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"report={args.json_output}")
    return 0 if not args.enforce_gate or report["quality_gate"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
