import pytest

from src.runtime.store import MemoryRuntimeStore
from src.services.plan_service import PlanService
from src.services.route_bundle_cache import route_bundle_cache


@pytest.mark.asyncio
async def test_rejected_poi_becomes_cross_session_avoidance():
    route_bundle_cache.clear()
    service = PlanService(store=MemoryRuntimeStore())
    first = await service.run_plan("徐汇区喝咖啡，预算100元", user_id="user-1", session_id="feedback-1")
    poi_id = first["route_results"][0]["route"]["stops"][0]["poi_id"]

    updated = await service.apply_feedback("feedback-1", action="reject_poi", poi_id=poi_id)
    profile = await service._store.load_profile("default", "user-1")
    second = await service.run_plan("徐汇区喝咖啡，预算100元", user_id="user-1", session_id="feedback-2")

    assert updated is not None
    assert poi_id in profile.avoided_poi_ids
    assert second["plan_path"] == "cold"
    assert poi_id not in {poi["poi_id"] for poi in second["candidate_pois"]}


@pytest.mark.asyncio
async def test_high_and_low_route_scores_update_profile_pois():
    service = PlanService(store=MemoryRuntimeStore())
    state = await service.run_plan("徐汇区喝咖啡，预算100元", user_id="user-2", session_id="feedback-rate")
    route = state["route_results"][0]["route"]
    poi_ids = [stop["poi_id"] for stop in route["stops"]]

    await service.apply_feedback("feedback-rate", action="rate", route_id=route["plan_id"], score=5)
    profile = await service._store.load_profile("default", "user-2")
    assert set(poi_ids) <= set(profile.liked_poi_ids)

    await service.apply_feedback("feedback-rate", action="rate", route_id=route["plan_id"], score=1)
    profile = await service._store.load_profile("default", "user-2")
    assert set(poi_ids) <= set(profile.avoided_poi_ids)
    assert not (set(profile.liked_poi_ids) & set(profile.avoided_poi_ids))
