from src.models.blueprint import ActivitySlot, ItineraryBlueprint, SlotTimeWindow
from src.models.constraints import Constraints, IntentDomain
from src.services.blueprint_feasibility import compile_blueprint_feasibility
from src.services.constraint_compiler import compile_constraints


def _constraints(query: str, **overrides):
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
    normalized, compiled = compile_constraints(Constraints(**values))
    return normalized, compiled


def test_precheck_repairs_lunch_conflict_by_reordering_optional_activity():
    constraints, compiled = _constraints("明天和女朋友在西湖附近玩一天")
    draft = ItineraryBlueprint(
        blueprint_id="bp-balanced",
        style="balanced",
        scene_type="couple",
        start_at="10:00",
        return_by="20:00",
        slots=[
            ActivitySlot(
                slot_id="walk", role="anchor", domain="sightseeing",
                categories=["湖边散步"], duration_minutes=120,
            ),
            ActivitySlot(
                slot_id="garden", role="optional", domain="sightseeing",
                categories=["园林"], duration_minutes=90,
            ),
            ActivitySlot(
                slot_id="lunch", role="meal", domain="dining",
                categories=["午餐"], duration_minutes=60, source="policy",
                time_window=SlotTimeWindow(start="11:30", end="13:30"),
            ),
            ActivitySlot(
                slot_id="culture", role="anchor", domain="sightseeing",
                categories=["文化体验"], duration_minutes=75,
            ),
        ],
    )

    blueprint, report = compile_blueprint_feasibility(draft, constraints, compiled)

    assert blueprint is not None
    assert report["status"] in {"feasible", "feasible_with_risk"}
    assert {item["action"] for item in report["repair_actions"]} == {
        "move_optional_after_policy"
    }
    slot_ids = [slot.slot_id for slot in blueprint.slots]
    assert "garden" in slot_ids
    assert slot_ids.index("lunch") < slot_ids.index("garden")
    lunch = next(slot for slot in blueprint.slots if slot.slot_id == "lunch")
    assert lunch.requirement_level == "policy"
    assert lunch.required is False
    assert lunch.expected_time_window is not None


def test_precheck_rejects_even_optimistic_hard_window_conflict():
    constraints, compiled = _constraints(
        "10点到12点，先散步再吃午餐",
        start_at="10:00",
        return_by="12:00",
        time_budget_minutes=120,
        explicit_activities=[
            {"domain_hint": "sightseeing", "modality": "required", "evidence": "散步"},
            {"domain_hint": "dining", "modality": "required", "evidence": "午餐"},
        ],
    )
    draft = ItineraryBlueprint(
        blueprint_id="bp-balanced",
        style="balanced",
        start_at="10:00",
        return_by="12:00",
        slots=[
            ActivitySlot(
                slot_id="walk", role="anchor", domain="sightseeing",
                categories=["散步"], duration_minutes=120,
                duration_min_minutes=120,
            ),
            ActivitySlot(
                slot_id="lunch", role="anchor", domain="dining",
                categories=["午餐"], duration_minutes=60,
                duration_min_minutes=60,
                time_window=SlotTimeWindow(start="11:30", end="12:00"),
            ),
        ],
    )

    blueprint, report = compile_blueprint_feasibility(draft, constraints, compiled)

    assert blueprint is None
    assert report["status"] == "infeasible"
    assert report["conflicts"][0]["failure_type"] == "temporal_conflict"


def test_generic_llm_activity_is_optional_not_hard():
    constraints, compiled = _constraints("在西湖附近玩一天")
    draft = ItineraryBlueprint(
        blueprint_id="bp-balanced",
        style="balanced",
        start_at="10:00",
        return_by="20:00",
        slots=[
            ActivitySlot(
                slot_id="leisure", role="anchor", domain="leisure",
                categories=["休闲体验"], duration_minutes=60, required=True,
            )
        ],
    )

    blueprint, _ = compile_blueprint_feasibility(draft, constraints, compiled)

    assert blueprint is not None
    assert blueprint.slots[0].requirement_level == "optional"
    assert blueprint.slots[0].required is False


def test_full_day_precheck_repairs_expected_schedule_within_maximum():
    constraints, compiled = _constraints("在西湖附近玩一天")
    draft = ItineraryBlueprint(
        blueprint_id="bp-balanced",
        style="balanced",
        start_at="10:00",
        return_by="20:30",
        slots=[
            ActivitySlot(
                slot_id=f"anchor-{index}",
                role="anchor",
                domain="sightseeing",
                categories=["城市体验"],
                duration_minutes=120,
            )
            for index in range(1, 7)
        ],
    )

    blueprint, report = compile_blueprint_feasibility(draft, constraints, compiled)

    assert blueprint is not None
    assert report["expected_duration_minutes"] <= 600
    assert report["repair_actions"]
