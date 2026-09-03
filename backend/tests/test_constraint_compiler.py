import pytest

from src.models.constraints import Constraints, IntentDomain
from src.services.constraint_compiler import compile_constraints


def _constraints(query: str, **overrides) -> Constraints:
    values = {
        "raw_query": query,
        "domains": [IntentDomain.SIGHTSEEING],
        "city": "杭州市",
        "location_mentions": ["西湖"],
        "time_budget_minutes": 180,
        "budget_per_person": 150,
        "poi_count": 3,
    }
    values.update(overrides)
    return Constraints(**values)


def test_full_day_compiles_to_soft_envelope_not_480_hard_minutes():
    normalized, compiled = compile_constraints(
        _constraints("明天和女朋友在西湖附近玩一天")
    )

    envelope = compiled.schedule_envelope
    assert envelope.time_scope == "full_day"
    assert (
        envelope.min_duration_minutes,
        envelope.target_duration_minutes,
        envelope.max_duration_minutes,
    ) == (420, 540, 600)
    assert envelope.flexibility == "soft"
    assert normalized.time_budget_minutes == 600
    assert normalized.time_budget_hard is False
    assert normalized.poi_count_target == 4
    assert not any(
        item.field == "target_duration_minutes"
        and item.value == 480
        and item.strength == "hard"
        for item in compiled.atoms
    )
    assert {item["policy_id"] for item in compiled.active_policies} >= {
        "meal-lunch",
        "meal-dinner",
    }


@pytest.mark.parametrize("expression", ["一整天", "整天", "全天", "玩一天"])
def test_full_day_variants_share_the_same_schedule_envelope(expression):
    normalized, compiled = compile_constraints(
        _constraints(f"明天和女朋友在西湖附近{expression}")
    )

    envelope = compiled.schedule_envelope
    assert envelope.time_scope == "full_day"
    assert (
        envelope.min_duration_minutes,
        envelope.target_duration_minutes,
        envelope.max_duration_minutes,
    ) == (420, 540, 600)
    assert normalized.time_expression_kind == "full_day"


def test_exact_duration_and_clock_window_remain_hard():
    duration, duration_compiled = compile_constraints(
        _constraints("在西湖玩3小时", time_budget_minutes=180)
    )
    assert duration.time_budget_hard is True
    assert duration_compiled.schedule_envelope.time_scope == "exact_duration"
    assert duration_compiled.schedule_envelope.max_duration_minutes == 180

    window, window_compiled = compile_constraints(
        _constraints(
            "在西湖10点到18点",
            start_at="10:00",
            return_by="18:00",
            time_budget_minutes=480,
        )
    )
    assert window.time_budget_hard is True
    assert window_compiled.schedule_envelope.time_scope == "clock_window"
    assert window_compiled.schedule_envelope.target_duration_minutes == 480


def test_named_nearby_location_is_hard_anchor_with_soft_radius_relation():
    _, compiled = compile_constraints(
        _constraints("在西湖附近玩一天", geo_relation="nearby")
    )

    anchor = next(item for item in compiled.atoms if item.field == "geo_anchor")
    relation = next(item for item in compiled.atoms if item.field == "geo_relation")
    assert anchor.strength == "hard"
    assert anchor.value == "西湖"
    assert relation.strength == "soft"
    assert relation.relax_policy == "expand_named_area_radius"


def test_default_budget_is_policy_while_explicit_cap_is_hard():
    _, default_compiled = compile_constraints(_constraints("在西湖玩一天"))
    _, capped_compiled = compile_constraints(
        _constraints("在西湖玩一天，人均不超过200", budget_per_person=200)
    )

    default_budget = next(item for item in default_compiled.atoms if item.field == "budget_per_person")
    capped_budget = next(item for item in capped_compiled.atoms if item.field == "budget_per_person")
    assert default_budget.strength == "policy"
    assert capped_budget.strength == "hard"


def test_explicit_no_meal_drops_meal_policy():
    _, compiled = compile_constraints(_constraints("西湖玩一天但不吃饭"))

    assert not any(item.get("policy_id") == "meal-lunch" for item in compiled.active_policies)
    assert compiled.dropped_policies == [
        {"policy_id": "meal-service", "reason": "explicit_no_meal"}
    ]
