import pytest

from src.graph.nodes.geo_resolve import geo_resolve
from src.graph.state import build_initial_state
from src.services.geo_resolver import (
    GeoCandidate,
    GeoResolver,
    GazetteerGeoProvider,
    extract_location_mentions,
)


def test_extract_location_mentions_from_gazetteer():
    assert extract_location_mentions("武康路附近咖啡") == ["武康路"]
    assert extract_location_mentions("外滩夜景加晚饭") == ["外滩"]


@pytest.mark.asyncio
async def test_gazetteer_resolves_business_area():
    resolver = GeoResolver(providers=[GazetteerGeoProvider()])

    scope = await resolver.resolve_geo_scope("武康路附近咖啡")

    assert scope.resolved_name == "武康路/安福路"
    assert scope.scope_type == "business_area"
    assert scope.district == "徐汇区"
    assert scope.business_area == "武康路/安福路"
    assert scope.center_lat is not None
    assert scope.center_lng is not None
    assert scope.radius_m == 1200
    assert scope.source == "gazetteer"


@pytest.mark.asyncio
async def test_explicit_location_mentions_override_query_extraction():
    resolver = GeoResolver(providers=[GazetteerGeoProvider()])

    scope = await resolver.resolve_geo_scope(
        "帮我找咖啡",
        location_mentions=["陆家嘴"],
    )

    assert scope.resolved_name == "陆家嘴"
    assert scope.district == "浦东新区"
    assert scope.business_area == "陆家嘴"


class FakeReverseProvider:
    async def search_place(self, keyword: str, *, city: str = "上海"):
        return []

    async def geocode(self, address: str, *, city: str = "上海"):
        return []

    async def reverse_geocode(self, lat: float, lng: float):
        return GeoCandidate(
            name="测试当前位置",
            place_type="current_location",
            district="静安区",
            lat=lat,
            lng=lng,
            radius_m=1500,
            confidence=0.9,
            source="fake_reverse",
        )


@pytest.mark.asyncio
async def test_nearby_uses_reverse_provider_when_available():
    resolver = GeoResolver(providers=[FakeReverseProvider()])

    scope = await resolver.resolve_geo_scope(
        "附近找个咖啡",
        user_lat=31.22,
        user_lng=121.45,
    )

    assert scope.resolved_name == "测试当前位置"
    assert scope.district == "静安区"
    assert scope.center_lat == 31.22
    assert scope.center_lng == 121.45
    assert scope.source == "fake_reverse"


@pytest.mark.asyncio
async def test_default_scope_when_no_location_signal():
    resolver = GeoResolver(providers=[GazetteerGeoProvider()])

    scope = await resolver.resolve_geo_scope("想吃日料")

    assert scope.source == "default"
    assert scope.district == "徐汇区"
    assert scope.assumptions


@pytest.mark.asyncio
async def test_geo_node_corrects_default_district_from_business_area():
    state = build_initial_state("我想在陆家嘴附近玩三个小时")
    state["constraints"] = {
        "raw_query": state["user_query"],
        "district": "徐汇区",
        "domains": ["sightseeing"],
        "budget_per_person": 150,
        "time_budget_minutes": 180,
        "poi_count": 3,
    }
    state["assumptions"] = [{
        "slot": "district", "assumed_value": "徐汇区", "source": "scene_default", "message": "默认徐汇区",
    }]

    update = await geo_resolve(state)

    assert update["geo_scope"]["resolved_name"] == "陆家嘴"
    assert update["constraints"]["district"] == "浦东新区"
    assert update["assumptions"][0]["slot"] == "district"
    assert update["assumptions"][0]["assumed_value"] == "浦东新区"
