import pytest

from src.graph.plan_graph import build_plan_graph
from src.graph.state import build_initial_state


@pytest.mark.asyncio
async def test_replan_from_an_empty_route_falls_back_to_a_fresh_plan():
    state = build_initial_state("我不想去公园")
    state["session_current_route"] = {
        "plan_id": "empty-plan",
        "stops": [],
        "total_duration_min": 0,
        "estimated_cost_per_person": 0,
    }
    state["memory_context"] = {
        "current_route": state["session_current_route"],
        "current_constraints": {"district": "黄浦区", "budget_per_person": 150},
        "recent_turns": [],
        "user_profile": {},
    }

    result = await build_plan_graph().compile().ainvoke(state, {"recursion_limit": 20})

    assert result["run_status"] == "completed"
    assert result["turn_relation"] == "new_goal"
    assert result["planning_outcome"] == "route_ready"
    assert result["route_results"]
    for route_result in result["route_results"]:
        assert all("公园" not in stop["category"] for stop in route_result["route"]["stops"])


@pytest.mark.asyncio
async def test_empty_route_replan_keeps_negative_category_out_of_fresh_plan():
    state = build_initial_state("我不想去博物馆")
    state["session_current_route"] = {
        "plan_id": "empty-plan",
        "stops": [],
        "total_duration_min": 0,
        "estimated_cost_per_person": 0,
    }
    state["memory_context"] = {
        "current_route": state["session_current_route"],
        "current_constraints": {
            "district": "黄浦区",
            "budget_per_person": 150,
            "domains": ["sightseeing"],
        },
        "recent_turns": [],
        "user_profile": {},
    }

    result = await build_plan_graph().compile().ainvoke(state, {"recursion_limit": 20})

    assert result["constraints"]["excluded_categories"] == ["博物馆"]
    for route_result in result["route_results"]:
        assert all("博物馆" not in stop["category"] for stop in route_result["route"]["stops"])
