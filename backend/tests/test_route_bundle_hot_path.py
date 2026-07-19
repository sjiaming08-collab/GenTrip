import pytest

from src.runtime.store import MemoryRuntimeStore
from src.services.plan_service import PlanService
from src.services.route_bundle_cache import route_bundle_cache


@pytest.mark.asyncio
async def test_second_equivalent_plan_uses_route_bundle_hot_path():
    route_bundle_cache.clear()
    service = PlanService(store=MemoryRuntimeStore())
    query = "徐汇区下午两点看展览再喝咖啡，18点前回，人均150"

    cold = await service.run_plan(query, session_id="bundle-cold")
    hot = await service.run_plan(query, session_id="bundle-hot")

    assert cold["plan_path"] == "cold"
    assert "route_bundle_ingest" in [entry["phase"] for entry in cold["phase_log"]]
    assert hot["plan_path"] == "hot"
    phases = [entry["phase"] for entry in hot["phase_log"]]
    assert "route_bundle_search" in phases
    assert "route_validate" in phases
    assert "bundle_rerank" in phases
    assert "poi_retrieve" not in phases
    assert "route_generate" not in phases
    assert "route_evaluate" not in phases
    assert hot["route_results"][0]["source"] == "BUNDLE_HIT"


@pytest.mark.asyncio
async def test_nearby_budget_uses_adapted_route_bundle_hot_path():
    route_bundle_cache.clear()
    service = PlanService(store=MemoryRuntimeStore())
    cold_query = "徐汇区下午两点看展览再喝咖啡，18点前回，人均150元"
    adapted_query = "徐汇区下午两点看展览再喝咖啡，18点前回，人均175元"

    cold = await service.run_plan(cold_query, session_id="bundle-adapted-cold")
    adapted = await service.run_plan(adapted_query, session_id="bundle-adapted-hot")

    assert cold["plan_path"] == "cold"
    assert adapted["plan_path"] == "hot"
    assert adapted["bundle_match_score"] < 1.0
    assert adapted["route_results"][0]["source"] == "BUNDLE_ADAPTED"
    assert "poi_retrieve" not in [entry["phase"] for entry in adapted["phase_log"]]


@pytest.mark.asyncio
async def test_business_area_route_is_not_cached_as_default_district_bundle():
    route_bundle_cache.clear()
    service = PlanService(store=MemoryRuntimeStore())

    business_area = await service.run_plan("我想在陆家嘴附近玩三个小时", session_id="bundle-business-area")
    district = await service.run_plan("我想在徐汇区附近玩三个小时", session_id="bundle-district")

    assert business_area["plan_path"] == "cold"
    assert business_area["geo_scope"]["scope_type"] == "business_area"
    assert district["plan_path"] == "cold"
    assert district.get("matched_bundle_id") is None
