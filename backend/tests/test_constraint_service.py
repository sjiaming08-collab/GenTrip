"""constraint_service + DeepSeek LLM 测试（mock，无需 API Key）。"""

from unittest.mock import AsyncMock, patch

import pytest

from src.config import settings
from src.graph.state import build_initial_state
from src.llm.exceptions import LLMError
from src.llm.schemas import ConstraintExtractResult, LlmAssumption
from src.models.constraints import IntentDomain
from src.services.constraint_compiler import compile_constraints
from src.services.constraint_service import extract, normalize_llm_result


def test_normalize_llm_result_fills_defaults():
    result = ConstraintExtractResult(
        domains=[IntentDomain.SIGHTSEEING],
        district=None,
        budget_per_person=None,
        time_budget_minutes=None,
    )
    constraints, assumptions = normalize_llm_result(result, "附近有什么好玩的")

    assert constraints.city == "上海"
    assert constraints.district is None
    assert constraints.budget_per_person == 150
    assert constraints.time_budget_minutes == 180
    assert constraints.domains == [IntentDomain.SIGHTSEEING]
    assert len(assumptions) >= 3


def test_normalize_llm_result_explicit():
    result = ConstraintExtractResult(
        domains=[IntentDomain.DINING, IntentDomain.SIGHTSEEING],
        district="黄浦区",
        budget_per_person=200,
        time_budget_minutes=180,
        activity_tags=["逛吃"],
        location_mentions=["南京西路", " 南京西路 ", "静安寺"],
        assumptions=[],
    )
    constraints, assumptions = normalize_llm_result(result, "黄浦区逛吃")

    assert constraints.district == "黄浦区"
    assert constraints.domains == [IntentDomain.DINING, IntentDomain.SIGHTSEEING]
    assert constraints.budget_per_person == 200
    assert constraints.location_mentions == ["南京西路", "静安寺"]
    assert assumptions == []


def test_normalize_accepts_arbitrary_city_and_district():
    result = ConstraintExtractResult(
        domains=[IntentDomain.SIGHTSEEING],
        city="杭州市",
        district="西湖区",
        location_mentions=["西湖"],
        budget_per_person=150,
        time_budget_minutes=180,
    )

    constraints, assumptions = normalize_llm_result(result, "杭州西湖区玩三个小时")

    assert constraints.city == "杭州市"
    assert constraints.district == "西湖区"
    assert constraints.location_mentions == ["西湖"]
    assert assumptions == []


def test_new_location_does_not_inherit_previous_district():
    state = build_initial_state("杭州西湖附近喝咖啡")
    state["memory_context"] = {
        "current_constraints": {"city": "上海市", "district": "黄浦区"},
    }
    result = ConstraintExtractResult(
        domains=[IntentDomain.DINING],
        city="杭州市",
        location_mentions=["西湖"],
        budget_per_person=100,
        time_budget_minutes=120,
    )

    constraints, _ = normalize_llm_result(result, state["user_query"], state)

    assert constraints.city == "杭州市"
    assert constraints.district is None


def test_coordinates_suppress_default_city_and_district():
    state = build_initial_state("附近吃饭", user_lat=31.22, user_lng=121.45)
    result = ConstraintExtractResult(
        domains=[IntentDomain.DINING],
        budget_per_person=100,
        time_budget_minutes=120,
    )

    constraints, assumptions = normalize_llm_result(result, state["user_query"], state)

    assert constraints.city is None
    assert constraints.district is None
    assert not any(item.slot in {"city", "district"} for item in assumptions)


def test_normalize_llm_result_recovers_explicit_time_when_llm_omits_it():
    result = ConstraintExtractResult(
        domains=[IntentDomain.SIGHTSEEING],
        district="黄浦区",
        budget_per_person=150,
        time_budget_minutes=None,
    )

    constraints, assumptions = normalize_llm_result(result, "黄浦区下午2点看展，18点前回")

    assert constraints.time_budget_minutes == 240
    assert constraints.start_at == "14:00"
    assert constraints.return_by == "18:00"
    assert any(item.slot == "time_budget_minutes" and item.source == "derived_time_window" for item in assumptions)


def test_normalize_llm_result_leaves_full_day_minutes_to_constraint_compiler():
    result = ConstraintExtractResult(
        contract_version=3,
        turn_mode="plan",
        domains_explicit=[IntentDomain.SIGHTSEEING],
        location_mentions_explicit=["黄浦区"],
        evidence={
            "domains_explicit": "玩",
            "location_mentions_explicit": "黄浦区",
        },
    )

    constraints, assumptions = normalize_llm_result(result, "黄浦区玩一天")
    normalized, compiled = compile_constraints(constraints)

    assert constraints.time_budget_minutes is None
    assert not any(item.slot == "time_budget_minutes" for item in assumptions)
    assert normalized.time_budget_minutes == 600
    assert normalized.poi_count_target == 4
    assert compiled.schedule_envelope.target_duration_minutes == 540


def test_normalize_llm_result_keeps_explicit_small_stop_count_for_full_day():
    result = ConstraintExtractResult(
        domains=[IntentDomain.SIGHTSEEING],
        district="黄浦区",
        budget_per_person=150,
        time_budget_minutes=480,
        poi_count=5,
    )

    constraints, _ = normalize_llm_result(result, "黄浦区玩一天，只安排2个地点")

    assert constraints.poi_count == 2


def test_explicit_negation_is_preserved_with_llm_selected_domain():
    result = ConstraintExtractResult(
        domains=[IntentDomain.DINING],
        district="徐汇区",
        budget_per_person=150,
        time_budget_minutes=180,
    )

    constraints, _ = normalize_llm_result(
        result,
        "我不去博物馆了，就是吃点东西，你重新为我规划一下呢",
    )

    assert constraints.domains == [IntentDomain.DINING]
    assert constraints.excluded_categories == ["博物馆"]


def test_normalize_llm_result_keeps_richer_llm_domains_over_rule_keywords():
    result = ConstraintExtractResult(
        domains=[IntentDomain.DINING, IntentDomain.LEISURE],
        district="黄浦区",
        budget_per_person=150,
        time_budget_minutes=180,
    )

    constraints, _ = normalize_llm_result(result, "黄浦区看展后想按摩再吃点东西")

    assert constraints.domains == [IntentDomain.DINING, IntentDomain.LEISURE]


def test_generic_play_does_not_create_an_unsupported_required_leisure_domain():
    query = "我明天想和女朋友在西湖附近玩一天"
    result = ConstraintExtractResult(
        contract_version=2,
        turn_mode="plan",
        domains_explicit=[IntentDomain.SIGHTSEEING, IntentDomain.LEISURE],
        location_mentions_explicit=["西湖"],
        time_budget_minutes_explicit=480,
        scene_type_explicit="couple",
        evidence={
            "domains_explicit": "玩",
            "location_mentions_explicit": "西湖",
            "time_budget_minutes_explicit": "玩一天",
            "scene_type_explicit": "女朋友",
        },
    )

    constraints, _ = normalize_llm_result(result, query)

    assert constraints.domains == [IntentDomain.SIGHTSEEING]


def test_v3_generic_play_activity_is_not_compiled_as_an_explicit_anchor():
    query = "明天和女朋友在西湖附近玩一天"
    result = ConstraintExtractResult(
        contract_version=3,
        turn_mode="plan",
        domains_explicit=[IntentDomain.LEISURE],
        geo_mentions=[{"text": "西湖", "relation": "nearby", "evidence": "西湖附近"}],
        time_expression={"kind": "full_day", "evidence": "玩一天"},
        activities=[{
            "text": "玩",
            "domain_hint": "leisure",
            "modality": "required",
            "evidence": "玩一天",
        }],
        scene_type_explicit="couple",
        evidence={
            "domains_explicit": "玩",
            "scene_type_explicit": "女朋友",
        },
    )

    constraints, _ = normalize_llm_result(result, query)

    assert constraints.domains == [IntentDomain.SIGHTSEEING]
    assert constraints.explicit_activities == []


def test_full_day_wording_does_not_create_a_default_three_hour_assumption():
    query = "明天和女朋友在西湖附近玩一整天"
    result = ConstraintExtractResult(
        contract_version=3,
        turn_mode="plan",
        domains_explicit=[IntentDomain.SIGHTSEEING],
        geo_mentions=[{"text": "西湖", "relation": "nearby", "evidence": "西湖附近"}],
        scene_type_explicit="couple",
        evidence={
            "domains_explicit": "玩",
            "scene_type_explicit": "女朋友",
        },
    )

    constraints, assumptions = normalize_llm_result(result, query)

    assert not any(item.slot == "time_budget_minutes" for item in assumptions)
    assert constraints.time_budget_minutes is None


@pytest.mark.asyncio
async def test_extract_rule_only_by_default():
    state = build_initial_state("附近有什么好玩的")
    constraints, assumptions = await extract(state)

    assert constraints.city == "上海"
    assert constraints.district is None
    assert constraints.domains == [IntentDomain.SIGHTSEEING]
    assert len(assumptions) == 3


@pytest.mark.asyncio
async def test_extract_llm_with_fallback(monkeypatch):
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(settings, "constraint_extract_mode", "llm_with_fallback")

    mock_result = ConstraintExtractResult(
        domains=[IntentDomain.DINING],
        district="静安区",
        budget_per_person=120,
        time_budget_minutes=120,
        preferred_cuisines=["日料"],
        assumptions=[
            LlmAssumption(
                slot="time_budget_minutes",
                assumed_value="120",
                message="默认 2 小时用餐",
            )
        ],
    )

    with patch(
        "src.services.constraint_service.llm_extract_constraint_with_meta",
        new=AsyncMock(return_value=(mock_result, {"operation": "constraint_extract", "status": "success"})),
    ):
        state = build_initial_state("静安日料")
        constraints, assumptions = await extract(state)

    assert constraints.district == "静安区"
    assert constraints.domains == [IntentDomain.DINING]
    assert constraints.budget_per_person == 120
    assert constraints.preferred_cuisines == ["日料"]
    assert assumptions == []


def test_v2_discards_fields_without_exact_query_evidence():
    result = ConstraintExtractResult(
        contract_version=2,
        domains_explicit=[IntentDomain.DINING],
        district_explicit="徐汇区",
        budget_per_person_explicit=800,
        time_budget_minutes_explicit=120,
        evidence={
            "domains_explicit": "吃饭",
            "district_explicit": "徐汇区",
            "time_budget_minutes_explicit": "两小时",
        },
    )

    constraints, assumptions = normalize_llm_result(result, "徐汇区吃饭两小时")

    assert constraints.district == "徐汇区"
    assert constraints.time_budget_minutes == 120
    assert constraints.budget_per_person == 150
    assert any(item.slot == "budget_per_person" for item in assumptions)


def test_v2_preserves_evidenced_open_vocabulary_exclusion():
    result = ConstraintExtractResult(
        contract_version=2,
        domains_explicit=[IntentDomain.DINING],
        excluded_categories_explicit=["网红店"],
        evidence={
            "domains_explicit": "吃饭",
            "excluded_categories_explicit": "不要网红店",
        },
    )

    constraints, _ = normalize_llm_result(result, "想吃饭，但不要网红店")

    assert constraints.excluded_categories == ["网红店"]


@pytest.mark.asyncio
async def test_extract_llm_fallback_on_error(monkeypatch):
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(settings, "constraint_extract_mode", "llm_with_fallback")

    with patch(
        "src.services.constraint_service.llm_extract_constraint_with_meta",
        new=AsyncMock(side_effect=LLMError("api down")),
    ):
        state = build_initial_state("徐汇逛吃")
        constraints, _ = await extract(state)

    assert constraints.district == "徐汇区"
    assert constraints.domains == [IntentDomain.DINING, IntentDomain.SIGHTSEEING]
