import pytest

from src.graph.nodes.auto_relax import auto_relax
from src.graph.state import build_initial_state


@pytest.mark.asyncio
async def test_auto_relax_widens_budget_time_and_geo_once():
    state = build_initial_state("徐汇逛吃")
    state["constraints"] = {
        "raw_query": "徐汇逛吃",
        "domains": ["dining"],
        "district": "徐汇区",
        "time_budget_minutes": 120,
        "return_by": "18:00",
        "budget_per_person": 100,
        "poi_count": 3,
    }
    state["assumptions"] = [
        {"slot": "budget_per_person", "assumed_value": "100", "source": "scene_default", "message": "默认预算"},
        {"slot": "time_budget_minutes", "assumed_value": "120", "source": "scene_default", "message": "默认时长"},
        {"slot": "district", "assumed_value": "徐汇区", "source": "scene_default", "message": "默认区域"},
    ]

    update = await auto_relax(state)

    assert update["relax_attempt"] == 1
    assert update["constraints"]["budget_per_person"] == 130
    assert update["constraints"]["time_budget_minutes"] == 180
    assert update["constraints"]["return_by"] == "18:00"
    assert update["constraints"]["district"] == "徐汇区"
    assert "geo_scope:citywide" in update["relaxed_constraints"]


@pytest.mark.asyncio
async def test_auto_relax_does_not_repeat_after_first_attempt():
    state = build_initial_state("徐汇逛吃")
    state["relax_attempt"] = 1
    state["constraints"] = {"budget_per_person": 100}

    update = await auto_relax(state)

    assert update["relax_attempt"] == 1
    assert "constraints" not in update
