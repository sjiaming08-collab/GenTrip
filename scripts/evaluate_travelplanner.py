"""Run the derived TravelPlanner suite through the real GenTrip graph."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from contextlib import nullcontext
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DEFAULT_CASES = BACKEND / "fixtures" / "travelplanner_gentrip_validation.json"
DEFAULT_POIS = BACKEND / "fixtures" / "travelplanner_pois.json"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from evaluate_route_plans import evaluate_case  # noqa: E402
from src.config import settings  # noqa: E402
from src.evaluation import RouteJudge  # noqa: E402
from src.evaluation.travelplanner import build_travelplanner_report  # noqa: E402
from src.graph.state import token_usage_from_calls  # noqa: E402
from src.runtime.events import RuntimeEventBus  # noqa: E402
from src.runtime.store import MemoryRuntimeStore  # noqa: E402
from src.services.plan_service import PlanService  # noqa: E402
from src.services.poi_retrieval import use_poi_fixture  # noqa: E402
from src.services.route_bundle_cache import route_bundle_cache  # noqa: E402


def load_cases(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError("TravelPlanner-derived case file must be a non-empty JSON list")
    return data


async def run_cases(
    cases: list[dict[str, Any]], *, live_llm: bool, poi_fixture: Path | None = None
) -> list[dict[str, Any]]:
    if live_llm and not settings.llm_api_key:
        raise RuntimeError("--live-llm requires a configured LLM API key")

    service = PlanService(store=MemoryRuntimeStore(), event_bus=RuntimeEventBus(""))
    original_llm_enabled = settings.llm_enabled
    original_redis_url = settings.redis_url
    settings.llm_enabled = bool(live_llm)
    settings.redis_url = ""
    route_bundle_cache.clear()
    try:
        results: list[dict[str, Any]] = []
        fixture_context = use_poi_fixture(poi_fixture) if poi_fixture else nullcontext()
        with fixture_context:
            for index, case in enumerate(cases, start=1):
                started = perf_counter()
                state = await service.run_plan(case["query"])
                elapsed_ms = round((perf_counter() - started) * 1000, 1)
                result = evaluate_case(case, state)
                result["runtime"] = {
                    "latency_ms": elapsed_ms,
                    "token_usage": token_usage_from_calls(state.get("llm_calls") or []),
                    "phase_count": len(state.get("phase_log") or []),
                    "llm_calls": [
                        {
                            key: call.get(key)
                            for key in ("operation", "status", "model", "latency_ms", "total_tokens")
                        }
                        for call in state.get("llm_calls") or []
                    ],
                }
                result["presentation"] = state.get("presentation")
                results.append(result)
                print(
                    f"[{index}/{len(cases)}] {case['id']} completed={result['is_completed']} "
                    f"legal={result['is_legal']} quality={result['quality_score']:.3f} "
                    f"latency={elapsed_ms:.0f}ms"
                )
        return results
    finally:
        settings.llm_enabled = original_llm_enabled
        settings.redis_url = original_redis_url
        route_bundle_cache.clear()


async def add_judgements(
    report: dict[str, Any], cases: list[dict[str, Any]]
) -> None:
    by_id = {case["id"]: case for case in cases}
    judge = RouteJudge()
    passed = 0
    scores: list[float] = []
    judge_tokens = 0
    judge_latencies: list[float] = []
    for item in report["cases"]:
        verdict = await judge.evaluate(by_id[item["id"]], item)
        payload = verdict.model_dump(mode="json")
        payload["normalized_score"] = verdict.normalized_score
        item["llm_judge"] = payload
        passed += verdict.verdict == "pass"
        scores.append(verdict.normalized_score)
        judge_tokens += int(verdict.model_meta.get("total_tokens") or 0)
        judge_latencies.append(float(verdict.model_meta.get("latency_ms") or 0))
    report["llm_judge"] = {
        "case_count": len(scores),
        "pass_rate": round(passed / max(len(scores), 1), 3),
        "mean_normalized_score": round(sum(scores) / max(len(scores), 1), 3),
        "total_tokens": judge_tokens,
        "mean_latency_ms": round(sum(judge_latencies) / max(len(judge_latencies), 1), 1),
    }
    report["summary"]["all_model_tokens"] = int(report["summary"]["total_tokens"]) + judge_tokens


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate GenTrip on a TravelPlanner-derived suite")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--limit", type=int, help="Evaluate only the first N cases")
    parser.add_argument("--case-id", action="append", help="Evaluate a specific case ID; repeatable")
    parser.add_argument("--live-llm", action="store_true", help="Use the configured live planner LLM")
    parser.add_argument("--llm-judge", action="store_true", help="Run the configured live LLM judge")
    parser.add_argument(
        "--poi-fixture",
        type=Path,
        default=DEFAULT_POIS,
        help="Isolated POI fixture used by the benchmark (set to an empty path to disable)",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=ROOT / ".runtime_logs" / "travelplanner-eval.json",
    )
    return parser.parse_args()


async def async_main(args: argparse.Namespace) -> dict[str, Any]:
    cases = load_cases(args.cases)
    if args.case_id:
        requested = set(args.case_id)
        cases = [case for case in cases if case["id"] in requested]
        missing = requested - {case["id"] for case in cases}
        if missing:
            raise ValueError(f"unknown case IDs: {sorted(missing)}")
    if args.limit is not None:
        if args.limit < 1:
            raise ValueError("--limit must be positive")
        cases = cases[: args.limit]
    poi_fixture = args.poi_fixture if args.poi_fixture and args.poi_fixture.exists() else None
    results = await run_cases(cases, live_llm=args.live_llm, poi_fixture=poi_fixture)
    report = build_travelplanner_report(cases, results, live_llm=args.live_llm)
    if args.llm_judge:
        if not settings.llm_api_key:
            raise RuntimeError("--llm-judge requires a configured LLM API key")
        await add_judgements(report, cases)
    return report


def main() -> int:
    args = parse_args()
    report = asyncio.run(async_main(args))
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"report={args.json_output}")
    print("official_travelplanner_score=null (derived compatibility protocol)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
