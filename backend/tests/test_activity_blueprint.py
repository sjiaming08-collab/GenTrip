import pytest

from src.config import settings
from src.graph.nodes.activity_blueprint import activity_blueprint
from src.graph.state import build_initial_state
from src.models.blueprint import ActivitySlot, ItineraryBlueprint
from src.models.constraints import Constraints, IntentDomain
from src.services.activity_blueprint_service import (
    apply_slot_policy,
    build_rule_blueprints,
    normalize_llm_blueprints,
)


def _constraints(query: str, **overrides) -> Constraints:
    values = {
        "raw_query": query,
        "domains": [IntentDomain.SIGHTSEEING],
        "city": "杭州市",
        "time_budget_minutes": 480,
        "budget_per_person": 150,
        "poi_count": 5,
        "poi_count_target": 5,
    }
    values.update(overrides)
    return Constraints(**values)


def test_couple_full_day_gets_two_blueprints_and_policy_slots():
    blueprints = build_rule_blueprints(_constraints("明天和女朋友在西湖附近玩一天"))

    assert [item.style for item in blueprints] == ["balanced", "experiential"]
    for blueprint in blueprints:
        assert blueprint.scene_type == "couple"
        assert sum(slot.role == "anchor" for slot in blueprint.slots) >= 3
        assert any(slot.role == "meal" and slot.categories == ["午餐"] for slot in blueprint.slots)
        assert any(slot.role == "optional" for slot in blueprint.slots)
        assert len(blueprint.slots) <= 8


def test_no_meal_request_disables_inferred_meals():
    blueprints = build_rule_blueprints(_constraints("西湖玩一天但不吃饭"))

    assert all(slot.role != "meal" for item in blueprints for slot in item.slots)


def test_three_hour_afternoon_does_not_force_meal():
    blueprints = build_rule_blueprints(
        _constraints(
            "下午三点玩三小时",
            start_at="15:00",
            time_budget_minutes=180,
            poi_count=3,
            poi_count_target=3,
        )
    )

    assert all(slot.role != "meal" for item in blueprints for slot in item.slots)


def test_route_crossing_evening_window_gets_dinner():
    blueprints = build_rule_blueprints(
        _constraints(
            "中午到晚上玩八小时",
            start_at="12:00",
            time_budget_minutes=480,
        )
    )

    assert all(
        any(slot.role == "meal" and slot.categories == ["晚餐"] for slot in item.slots)
        for item in blueprints
    )


def test_explicit_five_anchors_are_preserved_and_service_slots_do_not_count():
    blueprints = build_rule_blueprints(
        _constraints(
            "一天安排5个活动",
            anchor_count_explicit=5,
            poi_count=5,
            poi_count_target=5,
            poi_count_min=5,
            poi_count_max=5,
        )
    )

    for blueprint in blueprints:
        assert sum(slot.role == "anchor" for slot in blueprint.slots) == 5
        assert len(blueprint.slots) <= 8


def test_inferred_poi_target_is_not_a_hard_anchor_count():
    blueprints = build_rule_blueprints(
        _constraints(
            "徐家汇附近喝咖啡，2小时",
            domains=[IntentDomain.DINING],
            preferred_cuisines=["咖啡"],
            time_budget_minutes=120,
            poi_count=2,
            poi_count_target=2,
        )
    )

    for blueprint in blueprints:
        anchors = [slot for slot in blueprint.slots if slot.role == "anchor"]
        assert sum(slot.required for slot in anchors) == 1
        assert anchors[0].categories == ["咖啡"]


def test_llm_blueprint_is_not_padded_to_inferred_poi_target():
    constraints = _constraints(
        "静安区逛商场再吃饭，4小时，人均180元",
        domains=[IntentDomain.SHOPPING, IntentDomain.DINING],
        time_budget_minutes=240,
        poi_count=3,
        poi_count_target=3,
    )
    draft = ItineraryBlueprint(
        blueprint_id="draft",
        style="balanced",
        scene_type="solo",
        start_at="10:00",
        return_by="14:00",
        slots=[
            ActivitySlot(
                slot_id="shopping",
                role="anchor",
                required=True,
                domain=IntentDomain.SHOPPING,
                categories=["商场", "购物中心"],
                duration_minutes=90,
            ),
            ActivitySlot(
                slot_id="dining",
                role="anchor",
                required=True,
                domain=IntentDomain.DINING,
                categories=["餐厅"],
                duration_minutes=60,
            ),
        ],
    )

    normalized = normalize_llm_blueprints([draft], constraints)[0]
    anchors = [slot for slot in normalized.slots if slot.role == "anchor"]

    assert len(anchors) == 2
    assert {slot.domain for slot in anchors} == {
        IntentDomain.SHOPPING,
        IntentDomain.DINING,
    }
    assert all(slot.required for slot in anchors)


def test_full_day_llm_draft_is_supplemented_to_policy_density():
    constraints = _constraints(
        "明天和女朋友在西湖附近玩一天",
        time_expression_kind="full_day",
        time_budget_minutes=600,
        poi_count=4,
        poi_count_target=4,
    )
    draft = ItineraryBlueprint(
        blueprint_id="draft",
        style="balanced",
        scene_type="couple",
        start_at="09:30",
        return_by="20:30",
        slots=[
            ActivitySlot(
                slot_id="lake-walk",
                role="anchor",
                domain=IntentDomain.SIGHTSEEING,
                categories=["湖边散步"],
                duration_minutes=90,
            )
        ],
    )

    normalized = normalize_llm_blueprints([draft], constraints)[0]

    assert sum(slot.role == "anchor" for slot in normalized.slots) >= 3
    assert any(slot.role == "meal" for slot in normalized.slots)
    assert len(normalized.slots) <= 8


def test_policy_places_required_lunch_before_long_activities_miss_its_window():
    constraints = _constraints(
        "明天和女朋友在西湖附近玩一天",
        domains=[IntentDomain.SIGHTSEEING, IntentDomain.LEISURE],
        start_at="10:00",
        time_budget_minutes=480,
    )
    draft = ItineraryBlueprint(
        blueprint_id="bp-balanced",
        style="balanced",
        scene_type="couple",
        start_at="10:00",
        return_by="18:00",
        slots=[
            ActivitySlot(
                slot_id="lake-walk",
                role="anchor",
                required=True,
                domain=IntentDomain.SIGHTSEEING,
                categories=["湖边散步"],
                duration_minutes=120,
            ),
            ActivitySlot(
                slot_id="garden",
                role="optional",
                required=False,
                domain=IntentDomain.SIGHTSEEING,
                categories=["园林"],
                duration_minutes=90,
            ),
            ActivitySlot(
                slot_id="tea",
                role="optional",
                required=False,
                domain=IntentDomain.DINING,
                categories=["下午茶"],
                duration_minutes=60,
            ),
            ActivitySlot(
                slot_id="boat",
                role="optional",
                required=False,
                domain=IntentDomain.SIGHTSEEING,
                categories=["游船"],
                duration_minutes=60,
            ),
            ActivitySlot(
                slot_id="sunset",
                role="optional",
                required=False,
                domain=IntentDomain.SIGHTSEEING,
                categories=["日落观景"],
                duration_minutes=60,
            ),
            ActivitySlot(
                slot_id="leisure",
                role="anchor",
                required=True,
                domain=IntentDomain.LEISURE,
                categories=["休闲体验"],
                duration_minutes=60,
            ),
        ],
    )

    planned = apply_slot_policy(draft, constraints)
    lunch_index = next(
        index
        for index, slot in enumerate(planned.slots)
        if slot.slot_id == "balanced-meal-lunch"
    )

    assert lunch_index == 1
    assert planned.slots[lunch_index - 1].slot_id == "lake-walk"
    assert planned.slots[lunch_index - 1].role != "rest"


def test_rule_blueprint_preserves_explicit_domain_order():
    blueprints = build_rule_blueprints(
        _constraints(
            "徐汇区按摩放松再吃日料，5小时",
            domains=[IntentDomain.DINING, IntentDomain.LEISURE],
            preferred_cuisines=["日料"],
            time_budget_minutes=300,
            poi_count=4,
            poi_count_target=4,
        )
    )

    for blueprint in blueprints:
        required = [
            slot.domain
            for slot in blueprint.slots
            if slot.role == "anchor" and slot.required
        ]
        assert required == [IntentDomain.LEISURE, IntentDomain.DINING]


def test_return_by_without_start_uses_duration_to_derive_blueprint_start():
    blueprints = build_rule_blueprints(
        _constraints(
            "黄浦区看展再喝咖啡，18点前回",
            domains=[IntentDomain.SIGHTSEEING, IntentDomain.DINING],
            preferred_cuisines=["咖啡"],
            start_at=None,
            return_by="18:00",
            time_budget_minutes=180,
            poi_count=3,
            poi_count_target=3,
        )
    )

    assert all(item.start_at == "15:00" for item in blueprints)
    assert all(slot.role != "meal" for item in blueprints for slot in item.slots)


@pytest.mark.asyncio
async def test_blueprint_node_records_counts_and_one_llm_call(monkeypatch):
    monkeypatch.setattr(settings, "activity_blueprint_mode", "rule_only")
    state = build_initial_state("明天和女朋友在西湖附近玩一天")
    state["constraints"] = _constraints(state["user_query"]).model_dump(mode="json")

    update = await activity_blueprint(state)

    assert update["current_phase"] == "activity_blueprint"
    assert len(update["activity_blueprints"]) == 2
    assert len(update["llm_calls"]) == 1
    assert update["llm_calls"][0]["status"] == "skipped"
    assert update["phase_log"][0]["blueprint_count"] == 2
