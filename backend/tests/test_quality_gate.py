import pytest
from pydantic import ValidationError

from src.evaluation.judge import RouteJudge, RouteJudgeResult
from src.evaluation.quality_gate import build_quality_report


def _case(case_id: str, *, passed: bool = True, legal: bool = True, quality: float = 0.9):
    return {
        "id": case_id,
        "passed": passed,
        "is_completed": True,
        "is_legal": legal,
        "quality_score": quality,
    }


def test_quality_gate_enforces_suite_thresholds_and_hard_constraints():
    report = build_quality_report([_case("ok"), _case("illegal", passed=False, legal=False, quality=0.6)])

    assert report["passed"] is False
    assert report["summary"]["case_pass_rate"] == 0.5
    assert report["hard_constraint_failure_cases"] == ["illegal"]
    assert "hard_constraint_violations:1" in report["failures"]


def test_quality_gate_rejects_an_empty_suite():
    report = build_quality_report([])

    assert report["passed"] is False
    assert "empty_suite" in report["failures"]


class FakeJudgeClient:
    async def chat_json_with_meta(self, system, user, *, operation, temperature):
        assert operation == "route_quality_judge"
        assert temperature == 0.0
        return {
            "verdict": "pass",
            "scores": {
                "requirement_satisfaction": 5,
                "instruction_following": 4,
                "poi_grounding": 4,
                "route_coherence": 5,
                "explanation_quality": 3,
            },
            "hard_constraint_violations": [],
            "rationale": "The route satisfies the supplied constraints and uses grounded POIs.",
        }, {"model": "fake", "total_tokens": 10}


@pytest.mark.asyncio
async def test_route_judge_validates_and_scores_structured_output():
    result = await RouteJudge(FakeJudgeClient()).evaluate(
        {"query": "three hour route", "expect": {"min_stops": 2}},
        {"is_legal": True, "route": {"stop_count": 2}},
    )

    assert result.verdict == "pass"
    assert result.normalized_score == 0.84
    assert result.model_meta["total_tokens"] == 10


def test_route_judge_cannot_pass_with_a_hard_constraint_violation():
    with pytest.raises(ValidationError):
        RouteJudgeResult.model_validate({
            "verdict": "pass",
            "scores": {
                "requirement_satisfaction": 1,
                "instruction_following": 1,
                "poi_grounding": 1,
                "route_coherence": 1,
                "explanation_quality": 1,
            },
            "hard_constraint_violations": ["budget_exceeded"],
            "rationale": "Budget is exceeded.",
        })
