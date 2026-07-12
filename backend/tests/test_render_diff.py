import pytest

from src.graph.nodes.render_diff import render_diff
from src.graph.state import build_initial_state


def _stop(sequence: int, poi_id: str, name: str) -> dict:
    return {
        "sequence": sequence,
        "poi_id": poi_id,
        "poi_name": name,
        "category": "餐饮",
        "arrival_time": "10:00",
        "departure_time": "11:00",
        "visit_duration_min": 60,
        "travel_time_from_prev_min": 15,
    }


def _route(plan_id: str, stops: list[dict]) -> dict:
    return {
        "plan_id": plan_id,
        "plan_name": plan_id,
        "summary": plan_id,
        "stops": stops,
        "total_duration_min": 180,
        "estimated_cost_per_person": 150,
    }


@pytest.mark.asyncio
async def test_render_diff_reports_only_removed_stop_when_remaining_stops_shift_left():
    state = build_initial_state("我不想喝咖啡")
    state["original_route"] = _route("before", [
            _stop(1, "coffee", "南阳咖啡研习社"),
            _stop(2, "park", "襄阳公园"),
            _stop(3, "hotpot", "重庆老西门厨房"),
        ])
    state["valid_routes"] = [_route("after", [
            _stop(1, "park", "襄阳公园"),
            _stop(2, "hotpot", "重庆老西门厨房"),
        ])]
    state["replan_operation"] = {"type": "delete", "target_category": "咖啡"}

    result = await render_diff(state)
    changes = result["diff_result"]["changes"]

    assert [(item["type"], item["old_poi_name"], item["new_poi_name"]) for item in changes] == [
        ("removed", "南阳咖啡研习社", None),
        ("unchanged", "襄阳公园", "襄阳公园"),
        ("unchanged", "重庆老西门厨房", "重庆老西门厨房"),
    ]
    assert result["diff_result"]["summary"] == "去掉了第1站南阳咖啡研习社"
