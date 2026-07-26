"""constraint_service + DeepSeek LLM 测试（mock，无需 API Key）。"""

from unittest.mock import AsyncMock, patch

import pytest

from src.config import settings
from src.graph.state import build_initial_state
from src.llm.exceptions import LLMError
from src.llm.schemas import ConstraintExtractResult, LlmAssumption
from src.models.constraints import IntentDomain
from src.services.constraint_service import extract, normalize_llm_result


def test_normalize_llm_result_fills_defaults():
    result = ConstraintExtractResult(
        domains=[IntentDomain.SIGHTSEEING],
        district=None,
        budget_per_person=None,
        time_budget_minutes=None,
    )
    constraints, assumptions = normalize_llm_result(result, "附近有什么好玩的")

    assert constraints.district == "徐汇区"
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
        assumptions=[],
    )
    constraints, assumptions = normalize_llm_result(result, "黄浦区逛吃")

    assert constraints.district == "黄浦区"
    assert constraints.domains == [IntentDomain.DINING, IntentDomain.SIGHTSEEING]
    assert constraints.budget_per_person == 200
    assert assumptions == []


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


@pytest.mark.asyncio
async def test_extract_rule_only_by_default():
    state = build_initial_state("附近有什么好玩的")
    constraints, assumptions = await extract(state)

    assert constraints.district == "徐汇区"
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
    assert any(a.slot == "time_budget_minutes" for a in assumptions)


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
