from src.graph.state import build_initial_state
from src.llm.schemas import ConstraintExtractResult
from src.models.constraints import IntentDomain
from src.services.constraint_rules import detect_minutes, rule_based_extract
from src.services.constraint_service import normalize_llm_result


def test_detect_minutes_supports_chinese_duration_words():
    assert detect_minutes("\u73a9\u4e94\u4e2a\u5c0f\u65f6") == 300
    assert detect_minutes("\u4e24\u5c0f\u65f6\u534a") == 150
    assert detect_minutes("\u4e00\u4e2a\u534a\u5c0f\u65f6") == 90
    assert detect_minutes("\u4e5d\u5341\u5206\u949f") == 90


def test_rule_extractor_preserves_chinese_duration_without_defaulting():
    state = build_initial_state("\u9ec4\u6d66\u533a\u73a9\u4e94\u4e2a\u5c0f\u65f6")
    constraints, assumptions = rule_based_extract(state)

    assert constraints.time_budget_minutes == 300
    assert not any(item.slot == "time_budget_minutes" for item in assumptions)


def test_llm_normalization_uses_explicit_chinese_duration_when_model_omits_it():
    result = ConstraintExtractResult(
        domains=[IntentDomain.SIGHTSEEING],
        district="\u9ec4\u6d66\u533a",
        budget_per_person=150,
        time_budget_minutes=None,
    )

    constraints, _ = normalize_llm_result(result, "\u9ec4\u6d66\u533a\u73a9\u4e94\u4e2a\u5c0f\u65f6")

    assert constraints.time_budget_minutes == 300
