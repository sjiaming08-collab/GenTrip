import pytest

from src.graph.nodes.validate_delta import validate_delta
from src.graph.plan_graph import build_plan_graph
from src.graph.state import build_initial_state


@pytest.mark.asyncio
async def test_replan_replaces_an_unconfirmed_stop_when_direct_add_is_infeasible():
    state = build_initial_state("再加一家甜品")
    state["session_current_route"] = {
        "plan_id": "original-plan",
        "plan_name": "原路线",
        "summary": "两站路线",
        "estimated_cost_per_person": 90,
        "total_duration_min": 110,
        "stops": [
            {"sequence": 1, "poi_id": "cafe", "poi_name": "咖啡店", "category": "咖啡", "arrival_time": "14:00", "departure_time": "14:45", "visit_duration_min": 45, "travel_time_from_prev_min": 0},
            {"sequence": 2, "poi_id": "park", "poi_name": "公园", "category": "公园", "arrival_time": "15:00", "departure_time": "16:05", "visit_duration_min": 50, "travel_time_from_prev_min": 15},
        ],
    }
    state["memory_context"] = {
        "current_route": state["session_current_route"],
        "current_constraints": {"district": "徐汇区", "budget_per_person": 100, "time_budget_minutes": 120, "domains": ["dining"]},
        "recent_turns": [],
        "user_profile": {},
    }

    result = await build_plan_graph().compile().ainvoke(state, {"recursion_limit": 20})

    assert result["run_status"] == "completed"
    assert result["reply_type"] == "diff"
    assert result["planning_outcome"] == "change_applied"
    assert result["degraded"] is False
    route = result["route_results"][0]["route"]
    assert route["total_duration_min"] <= 120
    assert any("甜品" in stop["category"] or "甜品" in stop["poi_name"] for stop in route["stops"])


@pytest.mark.asyncio
async def test_generic_food_request_accepts_a_specific_dining_category():
    route = {
        "plan_id": "generic-food-route",
        "plan_name": "公园加正餐",
        "summary": "两站路线",
        "estimated_cost_per_person": 80,
        "total_duration_min": 134,
        "stops": [
            {"sequence": 1, "poi_id": "park", "poi_name": "襄阳公园", "category": "公园", "arrival_time": "09:30", "departure_time": "10:30", "visit_duration_min": 60, "travel_time_from_prev_min": 0},
            {"sequence": 2, "poi_id": "hotpot", "poi_name": "重庆老西门厨房", "category": "火锅", "arrival_time": "10:44", "departure_time": "11:44", "visit_duration_min": 45, "travel_time_from_prev_min": 14},
        ],
    }
    state = build_initial_state("我还想去吃东西呢")
    state.update({
        "constraints": {"budget_per_person": 150, "time_budget_minutes": 180, "excluded_categories": []},
        "candidate_routes": [route],
        "replan_operation": {"type": "add", "after_seq": 1, "new_cuisine": "美食"},
        "replan_operations": [{"type": "add", "after_seq": 1, "new_cuisine": "美食"}],
    })

    result = await validate_delta(state)

    assert result["delta_valid"] is True
    assert result["planning_outcome"] == "change_applied"
