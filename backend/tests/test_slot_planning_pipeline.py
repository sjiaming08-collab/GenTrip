import pytest

from src.config import settings
from src.graph.nodes.activity_blueprint import activity_blueprint
from src.graph.nodes.poi_retrieve import poi_retrieve
from src.graph.nodes.route_generate import route_generate
from src.graph.nodes.route_validate import route_validate
from src.graph.state import build_initial_state
from src.models.constraints import Constraints, IntentDomain
from src.models.route import RoutePlan, ScoredPoi
from src.services.travel_matrix import select_route_leg


def _full_day_constraints(query: str) -> Constraints:
    return Constraints(
        raw_query=query,
        domains=[IntentDomain.SIGHTSEEING],
        city="上海",
        time_budget_minutes=480,
        budget_per_person=200,
        poi_count=3,
        poi_count_target=3,
    )


@pytest.mark.asyncio
async def test_slot_retrieval_preserves_evidence_and_route_legs(monkeypatch):
    monkeypatch.setattr(settings, "activity_blueprint_mode", "rule_only")
    monkeypatch.setattr(settings, "poi_provider", "mock")
    monkeypatch.setattr(settings, "travel_time_provider", "mock")
    state = build_initial_state("和女朋友在上海玩一天")
    state["constraints"] = _full_day_constraints(state["user_query"]).model_dump(mode="json")

    blueprint_update = await activity_blueprint(state)
    state.update(blueprint_update)
    retrieval_update = await poi_retrieve(state)
    state.update(retrieval_update)

    assert retrieval_update["candidate_pois_by_slot"]
    assert all(len(items) <= 8 for items in retrieval_update["candidate_pois_by_slot"].values())
    for slot_id, candidates in retrieval_update["candidate_pois_by_slot"].items():
        for candidate in candidates:
            assert candidate["slot_id"] == slot_id
            assert candidate["provider"] == "fixture"
            assert candidate["field_sources"]["identity"] == "fixture"
            assert candidate["match_explanation"]

    generation_update = await route_generate(state)
    state.update(generation_update)
    assert generation_update["candidate_routes"], generation_update["route_generation_meta"]
    provider_ids = {
        candidate["poi_id"]
        for items in retrieval_update["candidate_pois_by_slot"].values()
        for candidate in items
    }
    for raw_route in generation_update["candidate_routes"]:
        route = RoutePlan.model_validate(raw_route)
        assert route.blueprint_id
        assert len(route.legs) == max(0, len(route.stops) - 1)
        assert {stop.poi_id for stop in route.stops} <= provider_ids
        assert all(leg.mode and leg.source and leg.confidence for leg in route.legs)

    validation_update = await route_validate(state)
    assert validation_update["validation_reports"]
    assert all(
        not any("交通段数量" in item for item in report["violations"])
        for report in validation_update["validation_reports"]
    )


@pytest.mark.asyncio
async def test_amap_unavailable_marks_travel_fallback(monkeypatch):
    monkeypatch.setattr(settings, "travel_time_provider", "amap")
    monkeypatch.setattr(settings, "amap_api_key", "")
    origin = ScoredPoi(
        poi_id="provider:a",
        name="A",
        category="观光",
        district="黄浦区",
        lat=31.2300,
        lng=121.4700,
        rating=4.5,
        price_per_person=0,
    )
    destination = origin.model_copy(
        update={"poi_id": "provider:b", "name": "B", "lat": 31.2350, "lng": 121.4750}
    )

    leg = await select_route_leg(
        origin,
        destination,
        budget_per_person=100,
    )

    assert leg.source == "mock_haversine"
    assert leg.estimated is True
    assert leg.fallback_used is True


@pytest.mark.asyncio
async def test_less_walking_preference_changes_medium_distance_mode(monkeypatch):
    monkeypatch.setattr(settings, "travel_time_provider", "mock")
    origin = ScoredPoi(
        poi_id="provider:a",
        name="A",
        category="观光",
        district="黄浦区",
        lat=31.2300,
        lng=121.4700,
        rating=4.5,
        price_per_person=0,
    )
    destination = origin.model_copy(
        update={"poi_id": "provider:b", "name": "B", "lat": 31.2480, "lng": 121.4700}
    )

    leg = await select_route_leg(
        origin,
        destination,
        budget_per_person=150,
        mobility_preferences=["少走路"],
    )

    assert 1200 < leg.distance_m < 5000
    assert leg.mode == "transit"
    assert leg.estimated is True
