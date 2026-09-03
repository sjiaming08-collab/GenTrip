import pytest

from src.graph.nodes.local_optimize import local_optimize
from src.graph.nodes.lock_confirmed import lock_confirmed
from src.graph.nodes.replan_parse import replan_parse
from src.graph.state import build_initial_state


def _route() -> dict:
    stops = []
    for sequence, (poi_id, role, source) in enumerate(
        [
            ("provider:anchor-1", "anchor", "inferred"),
            ("provider:lunch", "meal", "policy"),
            ("provider:anchor-2", "anchor", "inferred"),
        ],
        start=1,
    ):
        stops.append(
            {
                "sequence": sequence,
                "poi_id": poi_id,
                "poi_name": poi_id,
                "category": "本帮菜" if role == "meal" else "观光",
                "arrival_time": f"{9 + sequence:02d}:00",
                "departure_time": f"{10 + sequence:02d}:00",
                "visit_duration_min": 60,
                "travel_time_from_prev_min": 0 if sequence == 1 else 10,
                "queue_wait_min": 0,
                "lat": 31.2 + sequence / 100,
                "lng": 121.4 + sequence / 100,
                "slot_id": "bp-balanced-meal-lunch" if role == "meal" else f"bp-balanced-anchor-{sequence}",
                "slot_role": role,
                "slot_source": source,
                "slot_time_window": {"start": "11:30", "end": "13:30"} if role == "meal" else None,
            }
        )
    return {
        "plan_id": "route-1",
        "plan_name": "原路线",
        "summary": "原路线",
        "stops": stops,
        "total_duration_min": 200,
        "estimated_cost_per_person": 150,
    }


@pytest.mark.asyncio
async def test_remove_meal_deletes_only_inferred_meal_slot():
    state = build_initial_state("不要吃饭")
    state["turn_mode"] = "replan"
    state["session_current_route"] = _route()
    state["memory_context"] = {"current_constraints": {"budget_per_person": 150}}

    parsed = await replan_parse(state)
    state.update(parsed)
    assert parsed["replan_operations"][0]["target_slot_id"] == "bp-balanced-meal-lunch"

    locked = await lock_confirmed(state)
    state.update(locked)
    assert locked["locked_stop_indices"] == [0, 2]

    optimized = await local_optimize(state)
    assert optimized["candidate_routes"]
    remaining_ids = [item["poi_id"] for item in optimized["candidate_routes"][0]["stops"]]
    assert remaining_ids == ["provider:anchor-1", "provider:anchor-2"]


@pytest.mark.asyncio
async def test_replace_restaurant_targets_meal_slot_only():
    state = build_initial_state("换一家餐厅")
    state["turn_mode"] = "replan"
    state["session_current_route"] = _route()
    state["memory_context"] = {"current_constraints": {"budget_per_person": 150}}

    parsed = await replan_parse(state)
    state.update(parsed)
    operation = parsed["replan_operations"][0]
    assert operation["type"] == "replace"
    assert operation["target_seq"] == 2
    assert operation["target_slot_id"] == "bp-balanced-meal-lunch"

    locked = await lock_confirmed(state)
    assert locked["locked_stop_indices"] == [0, 2]
    assert locked["unlocked_slots"][0]["slot_id"] == "bp-balanced-meal-lunch"


@pytest.mark.asyncio
async def test_scoped_lunch_constraint_replaces_lunch_slot_and_preserves_anchors():
    state = build_initial_state("中午想吃正餐")
    state["turn_mode"] = "replan"
    state["session_current_route"] = _route()
    state["memory_context"] = {"current_constraints": {"budget_per_person": 150}}

    parsed = await replan_parse(state)
    state.update(parsed)
    operation = parsed["replan_operations"][0]

    assert operation["type"] == "replace"
    assert operation["target_seq"] == 2
    assert operation["target_slot_id"] == "bp-balanced-meal-lunch"
    assert operation["new_cuisine"] == "正餐"

    locked = await lock_confirmed(state)
    assert locked["locked_stop_indices"] == [0, 2]
    assert locked["unlocked_slots"][0]["slot_id"] == "bp-balanced-meal-lunch"
    assert locked["unlocked_slots"][0]["new_cuisine"] == "正餐"
