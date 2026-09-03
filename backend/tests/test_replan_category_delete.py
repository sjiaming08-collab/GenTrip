import pytest

from src.graph.nodes.local_optimize import local_optimize
from src.graph.nodes.lock_confirmed import lock_confirmed
from src.graph.nodes.partial_retrieval import _anchor_for_slot
from src.graph.nodes.replan_parse import replan_parse
from src.graph.state import build_initial_state


def _stop(sequence: int, category: str, name: str) -> dict:
    return {
        "sequence": sequence,
        "poi_id": name,
        "poi_name": name,
        "category": category,
        "arrival_time": "10:00",
        "departure_time": "11:00",
        "visit_duration_min": 60,
        "travel_time_from_prev_min": 15,
    }


def test_replan_retrieval_anchor_uses_the_adjacent_route_stop():
    stops = [
        {**_stop(1, "公园", "公园"), "lat": 31.20, "lng": 121.43},
        {**_stop(2, "观光", "街区"), "lat": 31.21, "lng": 121.44},
    ]

    assert _anchor_for_slot(stops, {"after_seq": 2}) == (31.21, 121.44)
    assert _anchor_for_slot(stops, {"sequence": 1}) == (31.20, 121.43)


@pytest.mark.asyncio
async def test_category_delete_removes_every_matching_stop_and_persists_exclusion():
    state = build_initial_state("我不想喝咖啡")
    state["session_current_route"] = {"stops": [_stop(1, "咖啡", "咖啡 A"), _stop(2, "公园", "公园"), _stop(3, "咖啡", "咖啡 B")]}
    state["memory_context"] = {"current_constraints": {"district": "徐汇区"}}

    parsed = await replan_parse(state)
    optimized = await local_optimize({**state, **parsed})

    assert parsed["constraints"]["excluded_categories"] == ["咖啡"]
    assert [stop["category"] for stop in optimized["valid_routes"][0]["stops"]] == ["公园"]


@pytest.mark.asyncio
async def test_ordinal_delete_is_not_treated_as_category_exclusion():
    state = build_initial_state("我不想去第1站")
    state["session_current_route"] = {"stops": [_stop(1, "寿司", "寿司店"), _stop(2, "公园", "公园")]}

    parsed = await replan_parse(state)
    optimized = await local_optimize({**state, **parsed})

    assert parsed["replan_operation"]["target_category"] is None
    assert [stop["poi_name"] for stop in optimized["valid_routes"][0]["stops"]] == ["公园"]


@pytest.mark.asyncio
async def test_delete_category_and_request_cuisine_replaces_the_removed_stop():
    state = build_initial_state("我不想去美术馆，想吃日料")
    state["session_current_route"] = {
        "stops": [_stop(1, "美术馆", "当代美术馆"), _stop(2, "公园", "襄阳公园")],
    }
    state["memory_context"] = {"current_constraints": {"district": "徐汇区"}}

    parsed = await replan_parse(state)
    locked = await lock_confirmed({**state, **parsed})
    optimized = await local_optimize({
        **state,
        **parsed,
        **locked,
        "replacement_candidates": [{
            "poi_id": "japanese-1", "name": "日料店", "category": "日料", "price_per_person": 120,
        }],
    })

    assert parsed["replan_operation"] == {
        "type": "replace",
        "target_seq": 1,
        "target_category": "美术馆",
        "new_cuisine": "日料",
        "exclude_category": "美术馆",
        "confidence": 1.0,
        "source": "rule_fallback",
    }
    assert parsed["constraints"]["excluded_categories"] == ["美术馆"]
    assert locked["unlocked_slots"][0]["new_cuisine"] == "日料"
    assert [stop["category"] for stop in optimized["valid_routes"][0]["stops"]] == ["日料", "公园"]


@pytest.mark.asyncio
async def test_model_operation_list_executes_delete_then_add():
    state = build_initial_state("删除美术馆，再加一家日料")
    state["session_current_route"] = {
        "stops": [_stop(1, "美术馆", "当代美术馆"), _stop(2, "公园", "襄阳公园")],
    }
    state["replan_operations"] = [
        {"type": "delete", "target_seq": 1, "target_category": "美术馆"},
        {"type": "add", "after_seq": 1, "new_cuisine": "日料"},
    ]
    state["memory_context"] = {"current_constraints": {"district": "徐汇区"}}

    parsed = await replan_parse(state)
    locked = await lock_confirmed({**state, **parsed})
    optimized = await local_optimize({
        **state,
        **parsed,
        **locked,
        "replacement_candidates": [
            {
                "poi_id": "japanese-1", "name": "日料店 A", "category": "日料",
                "price_per_person": 120, "_replan_operation_index": 1,
            },
            {
                "poi_id": "japanese-2", "name": "日料店 B", "category": "日料",
                "price_per_person": 100, "_replan_operation_index": 1,
            },
        ],
    })

    assert [item["type"] for item in parsed["replan_operations"]] == ["delete", "add"]
    assert parsed["constraints"]["excluded_categories"] == ["美术馆"]
    assert [stop["category"] for stop in optimized["valid_routes"][0]["stops"]] == ["公园", "日料"]
    assert len(optimized["candidate_routes"]) == 2
    assert {route["stops"][-1]["poi_id"] for route in optimized["candidate_routes"]} == {"japanese-1", "japanese-2"}


@pytest.mark.asyncio
async def test_replan_parse_prefers_canonical_turn_plan_operations():
    state = build_initial_state("再增加一家日料")
    state["session_current_route"] = {
        "stops": [_stop(1, "公园", "襄阳公园"), _stop(2, "咖啡", "社区咖啡")],
    }
    state["replan_operations"] = [{"type": "delete", "target_seq": 1}]
    state["turn_plan"] = {
        "mode": "replan",
        "operations": [{"type": "add", "after_seq": 2, "new_cuisine": "日料", "source": "llm"}],
    }

    parsed = await replan_parse(state)

    assert [item["type"] for item in parsed["replan_operations"]] == ["add"]
    assert parsed["turn_plan"]["operations"] == parsed["replan_operations"]
    assert parsed["turn_plan"]["preserve_unmentioned_stops"] is True


@pytest.mark.asyncio
async def test_explicit_replan_request_rebuilds_current_goal_with_lineage():
    state = build_initial_state("我不去博物馆了，就是吃点东西，你重新为我规划一下呢")
    state["session_current_route"] = {
        "stops": [_stop(1, "公园", "襄阳公园"), _stop(2, "博物馆", "思南公馆")],
    }
    state["replan_operations"] = [
        {"type": "delete", "target_seq": 2, "target_category": "博物馆"},
        {"type": "add", "after_seq": 1, "new_cuisine": "美食"},
    ]
    state["memory_context"] = {
        "current_constraints": {
            "district": "徐汇区", "domains": ["sightseeing"], "time_budget_minutes": 180,
        },
    }

    parsed = await replan_parse(state)

    assert parsed["turn_mode"] == "replan"
    assert parsed["run_mode"] == "replan"
    assert parsed["turn_relation"] == "modify_current"
    assert parsed["recompute_scope"] == "global_rebuild"
    assert parsed["constraints"]["district"] == "徐汇区"
    assert parsed["turn_plan"]["mode"] == "replan"
    assert parsed["turn_plan"]["operations"] == []
    assert parsed["turn_plan"]["preserve_unmentioned_stops"] is True


@pytest.mark.asyncio
async def test_generic_food_followup_has_rule_based_add_fallback():
    state = build_initial_state("我还想去吃东西呢")
    state["session_current_route"] = {
        "stops": [_stop(1, "公园", "襄阳公园"), _stop(2, "博物馆", "思南公馆")],
    }
    state["memory_context"] = {"current_constraints": {"district": "徐汇区"}}

    parsed = await replan_parse(state)

    assert parsed["replan_operation"]["type"] == "add"
    assert parsed["replan_operation"]["new_cuisine"] == "美食"
    assert parsed["replan_operation"]["source"] == "rule_fallback"
