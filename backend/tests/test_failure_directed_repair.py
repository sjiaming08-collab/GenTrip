import pytest

from src.graph.nodes.failure_directed_repair import failure_directed_repair
from src.graph.state import build_initial_state


@pytest.mark.asyncio
async def test_temporal_failure_drops_optional_without_touching_named_geo():
    state = build_initial_state("在西湖附近玩一天")
    state["constraints"] = {
        "raw_query": state["user_query"],
        "domains": ["sightseeing"],
        "city": "杭州市",
        "location_mentions": ["西湖"],
        "time_budget_minutes": 600,
        "budget_per_person": 150,
        "poi_count": 4,
    }
    state["geo_scope"] = {
        "resolved_name": "西湖",
        "city": "杭州市",
        "radius_m": 2000,
    }
    state["activity_blueprints"] = [{
        "blueprint_id": "bp-balanced",
        "slots": [
            {"slot_id": "hard", "requirement_level": "hard", "role": "anchor"},
            {"slot_id": "tea", "requirement_level": "optional", "role": "optional"},
        ],
    }]
    state["planning_failures"] = [{
        "failure_type": "temporal_conflict",
        "slot_id": "hard",
    }]

    update = await failure_directed_repair(state)

    assert update["repair_applied"] is True
    assert update["repair_actions"][0]["action"] == "drop_optional"
    assert update["geo_scope"]["resolved_name"] == "西湖"
    assert update["constraints"]["city"] == "杭州市"


@pytest.mark.asyncio
async def test_missing_candidate_expands_only_named_area_radius():
    state = build_initial_state("在西湖附近玩一天")
    state["constraints"] = {
        "raw_query": state["user_query"],
        "domains": ["sightseeing"],
        "city": "杭州市",
        "location_mentions": ["西湖"],
        "time_budget_minutes": 600,
        "budget_per_person": 150,
        "poi_count": 4,
    }
    state["geo_scope"] = {
        "resolved_name": "西湖",
        "city": "杭州市",
        "radius_m": 2000,
    }
    state["retrieval_meta"] = {"missing_required_slots": ["museum"]}

    update = await failure_directed_repair(state)

    assert update["geo_scope"]["resolved_name"] == "西湖"
    assert update["geo_scope"]["city"] == "杭州市"
    assert update["geo_scope"]["radius_m"] == 3000
    assert update["repair_actions"][0]["action"] == "expand_named_area_radius"


@pytest.mark.asyncio
async def test_hard_budget_is_never_relaxed():
    state = build_initial_state("人均不超过100元")
    state["constraints"] = {
        "raw_query": state["user_query"],
        "domains": ["dining"],
        "time_budget_minutes": 180,
        "budget_per_person": 100,
        "poi_count": 2,
    }
    state["compiled_constraints"] = {
        "atoms": [{"field": "budget_per_person", "strength": "hard"}],
    }
    state["planning_failures"] = [{"failure_type": "budget_conflict"}]

    update = await failure_directed_repair(state)

    assert update["repair_applied"] is False
    assert update["constraints"]["budget_per_person"] == 100
