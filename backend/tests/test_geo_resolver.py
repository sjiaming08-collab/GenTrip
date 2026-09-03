import httpx
import pytest

from src.config import settings
from src.graph.nodes.geo_resolve import geo_resolve
from src.graph.state import build_initial_state
from src.services.geo_resolver import (
    GeoCandidate,
    GeoResolver,
    GeoScope,
    GazetteerGeoProvider,
    AmapGeoProvider,
    build_default_geo_providers,
    extract_location_mentions,
)
from src.services.coordinates import wgs84_to_gcj02


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


class FakeSearchProvider:
    def __init__(self, candidate: GeoCandidate | None) -> None:
        self.candidate = candidate
        self.search_calls: list[str] = []

    async def search_place(self, keyword: str, *, city: str = "上海"):
        self.search_calls.append(keyword)
        return [self.candidate] if self.candidate else []

    async def geocode(self, address: str, *, city: str = "上海"):
        return []

    async def reverse_geocode(self, lat: float, lng: float):
        return None


@pytest.mark.asyncio
async def test_gazetteer_hit_short_circuits_remote_provider():
    remote = FakeSearchProvider(None)
    resolver = GeoResolver(providers=[GazetteerGeoProvider(), remote])

    scope = await resolver.resolve_geo_scope("武康路喝咖啡", location_mentions=["武康路"])

    assert scope.source == "gazetteer"
    assert remote.search_calls == []


@pytest.mark.asyncio
async def test_gazetteer_miss_falls_back_to_next_provider():
    remote = FakeSearchProvider(GeoCandidate(
        name="上海自然博物馆",
        district="静安区",
        lat=31.236,
        lng=121.463,
        source="remote",
    ))
    resolver = GeoResolver(providers=[GazetteerGeoProvider(), remote])

    scope = await resolver.resolve_geo_scope(
        "去上海自然博物馆附近",
        location_mentions=["上海自然博物馆"],
    )

    assert remote.search_calls == ["上海自然博物馆"]
    assert scope.source == "remote"
    assert scope.coord_system == "wgs84"


def test_default_provider_order_enables_amap_only_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "amap_api_key", "configured-key")

    providers = build_default_geo_providers()

    assert [type(provider) for provider in providers] == [GazetteerGeoProvider, AmapGeoProvider]


@pytest.mark.asyncio
async def test_amap_geo_provider_normalizes_place_to_wgs84():
    wgs_lat, wgs_lng = 31.2304, 121.4737
    gcj_lat, gcj_lng = wgs84_to_gcj02(wgs_lat, wgs_lng)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v3/place/text"
        return httpx.Response(200, json={
            "status": "1",
            "info": "OK",
            "pois": [{
                "id": "B001",
                "name": "测试地点",
                "location": f"{gcj_lng},{gcj_lat}",
                "adname": "黄浦区",
            }],
        })

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://restapi.amap.com",
    ) as client:
        candidates = await AmapGeoProvider("test-key", client=client).search_place("测试地点")

    assert candidates[0].lat == pytest.approx(wgs_lat, abs=1e-6)
    assert candidates[0].lng == pytest.approx(wgs_lng, abs=1e-6)
    assert candidates[0].coord_system == "wgs84"


@pytest.mark.asyncio
async def test_amap_geo_search_is_nationwide_without_city_hint():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "city" not in request.url.params
        assert "citylimit" not in request.url.params
        return httpx.Response(200, json={"status": "1", "info": "OK", "pois": []})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://restapi.amap.com",
    ) as client:
        await AmapGeoProvider("test-key", client=client).search_place("西湖", city=None)


@pytest.mark.asyncio
async def test_amap_reverse_geocode_converts_wgs84_request_to_gcj02():
    wgs_lat, wgs_lng = 31.2304, 121.4737
    expected_lat, expected_lng = wgs84_to_gcj02(wgs_lat, wgs_lng)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v3/geocode/regeo"
        assert request.url.params["location"] == f"{expected_lng},{expected_lat}"
        return httpx.Response(200, json={
            "status": "1",
            "info": "OK",
            "regeocode": {
                "formatted_address": "上海市黄浦区测试地址",
                "addressComponent": {"district": "黄浦区"},
            },
        })

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://restapi.amap.com",
    ) as client:
        candidate = await AmapGeoProvider("test-key", client=client).reverse_geocode(
            wgs_lat,
            wgs_lng,
        )

    assert candidate is not None
    assert candidate.lat == wgs_lat
    assert candidate.lng == wgs_lng
    assert candidate.coord_system == "wgs84"


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
    assert scope.scope_type == "city"
    assert scope.city == "上海"
    assert scope.district is None
    assert scope.assumptions


@pytest.mark.asyncio
async def test_user_coordinates_are_used_without_nearby_keyword():
    resolver = GeoResolver(providers=[FakeReverseProvider()])

    scope = await resolver.resolve_geo_scope(
        "想吃日料",
        user_lat=31.22,
        user_lng=121.45,
    )

    assert scope.source == "fake_reverse"
    assert scope.center_lat == 31.22
    assert scope.center_lng == 121.45


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
    assumptions = {item["slot"]: item for item in update["assumptions"]}
    assert assumptions["district"]["assumed_value"] == "浦东新区"


@pytest.mark.asyncio
async def test_geo_node_forwards_llm_location_mentions(monkeypatch):
    captured: dict = {}

    async def fake_resolve(self, query: str, **kwargs):
        captured.update(kwargs)
        return GeoScope(
            raw_mentions=kwargs["location_mentions"],
            resolved_name="上海自然博物馆",
            scope_type="poi",
            district="静安区",
            center_lat=31.236,
            center_lng=121.463,
            confidence=0.9,
            source="amap_place_search",
        )

    monkeypatch.setattr(GeoResolver, "resolve_geo_scope", fake_resolve)
    state = build_initial_state("上海自然博物馆附近吃饭")
    state["constraints"] = {
        "raw_query": state["user_query"],
        "district": "徐汇区",
        "domains": ["dining"],
        "budget_per_person": 150,
        "time_budget_minutes": 180,
        "poi_count": 3,
        "location_mentions": ["上海自然博物馆"],
    }

    update = await geo_resolve(state)

    assert captured["location_mentions"] == ["上海自然博物馆"]
    assert update["geo_scope"]["coord_system"] == "wgs84"
