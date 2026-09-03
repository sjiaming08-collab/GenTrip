"""Suite-level release gate built on deterministic route evaluation results."""

from __future__ import annotations

from statistics import mean
from typing import Any


DEFAULT_THRESHOLDS: dict[str, float | bool] = {
    "minimum_case_pass_rate": 1.0,
    "minimum_mean_quality_score": 0.78,
    "zero_hard_constraint_violations": True,
}


def build_quality_report(
    results: list[dict[str, Any]],
    thresholds: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Aggregate case results and return an explicit pass/fail release decision."""
    configured = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    case_count = len(results)
    passed_count = sum(bool(item.get("passed")) for item in results)
    pass_rate = passed_count / case_count if case_count else 0.0
    mean_quality = mean(float(item.get("quality_score") or 0.0) for item in results) if results else 0.0
    hard_failures = [
        str(item.get("id"))
        for item in results
        if item.get("is_completed") and not item.get("is_legal")
    ]

    failures: list[str] = []
    if not results:
        failures.append("empty_suite")
    if pass_rate < float(configured["minimum_case_pass_rate"]):
        failures.append(
            f"case_pass_rate:{pass_rate:.3f}<{float(configured['minimum_case_pass_rate']):.3f}"
        )
    if mean_quality < float(configured["minimum_mean_quality_score"]):
        failures.append(
            f"mean_quality_score:{mean_quality:.3f}<{float(configured['minimum_mean_quality_score']):.3f}"
        )
    if configured["zero_hard_constraint_violations"] and hard_failures:
        failures.append(f"hard_constraint_violations:{len(hard_failures)}")

    return {
        "passed": not failures,
        "thresholds": configured,
        "summary": {
            "case_count": case_count,
            "passed_count": passed_count,
            "case_pass_rate": round(pass_rate, 3),
            "mean_quality_score": round(mean_quality, 3),
            "hard_constraint_failure_count": len(hard_failures),
        },
        "hard_constraint_failure_cases": hard_failures,
        "failures": failures,
        "cases": results,
    }
