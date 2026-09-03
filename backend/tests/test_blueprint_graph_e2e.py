import pytest

from src.config import settings
from src.graph.plan_graph import create_plan_agent
from src.graph.state import build_initial_state
from src.services.route_bundle_cache import route_bundle_cache


@pytest.mark.asyncio
async def test_blueprint_enabled_cold_graph_produces_provider_backed_leg_complete_route(monkeypatch):
    monkeypatch.setattr(settings, "llm_enabled", False)
    monkeypatch.setattr(settings, "planner_blueprint_enabled", True)
    monkeypatch.setattr(settings, "activity_blueprint_mode", "rule_only")
    monkeypatch.setattr(settings, "poi_provider", "mock")
    monkeypatch.setattr(settings, "travel_time_provider", "mock")
    route_bundle_cache.clear()

    final = await create_plan_agent().ainvoke(
        build_initial_state("和女朋友在上海玩一天")
    )

    phases = [item["phase"] for item in final["phase_log"]]
    assert final["run_status"] == "completed"
    assert phases.index("activity_blueprint") < phases.index("poi_retrieve")
    assert len(final["activity_blueprints"]) == 2
    assert final["route_results"]
    provider_ids = {item["poi_id"] for item in final["candidate_pois"]}
    for result in final["route_results"]:
        route = result["route"]
        assert route["blueprint_id"]
        assert len(route["legs"]) == len(route["stops"]) - 1
        assert {stop["poi_id"] for stop in route["stops"]} <= provider_ids
