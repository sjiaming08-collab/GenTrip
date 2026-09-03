import asyncio
import httpx
import pytest

from src.models.constraints import IntentDomain
from src.models.retrieval import DomainSpec, RetrievalFilters, RetrievalPlan
from src.config import settings
from src.services.amap_poi_provider import AmapPoiProvider, AmapPoiProviderError
from src.services.coordinates import gcj02_to_wgs84, wgs84_to_gcj02
from src.services import poi_retrieval
from src.services.category_taxonomy import DEFAULT_MEAL_CATEGORIES


def _plan(*, nearby: bool = False) -> RetrievalPlan:
    return RetrievalPlan(
        raw_query="黄浦区吃日料",
        filters=RetrievalFilters(
            district="黄浦区",
            center_lat=31.2304 if nearby else None,
            center_lng=121.4737 if nearby else None,
            radius_m=1800 if nearby else None,
        ),
        domains=[DomainSpec(domain=IntentDomain.DINING, categories=["日料"])],
    )


@pytest.mark.asyncio
async def test_amap_provider_normalizes_live_poi_without_leaking_provider_shape():
    seen_request = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_request["path"] = request.url.path
        seen_request["query"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={
                "status": "1",
                "info": "OK",
                "infocode": "10000",
                "pois": [{
                    "id": "B001",
                    "name": "测试寿司店",
                    "type": "餐饮服务;外国餐厅;日本料理",
                    "typecode": "050200",
                    "location": "121.480000,31.230000",
                    "adname": "黄浦区",
                    "business_area": "人民广场",
                    "address": "测试路1号",
                    "business": {
                        "rating": "4.7",
                        "cost": "128",
                        "opentime_today": "11:00-22:00",
                    },
                }],
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://restapi.amap.com",
    )
    provider = AmapPoiProvider("test-key", client=client)
    try:
        pois = await provider.fetch_for_plan(_plan())
    finally:
        await client.aclose()

    assert seen_request["path"] == "/v3/place/text"
    assert seen_request["query"]["city"] == "黄浦区"
    assert seen_request["query"]["keywords"] == "日料"
    assert pois[0]["poi_id"] == "B001"
    assert pois[0]["source"] == "amap"
    assert pois[0]["category"] == "日料"
    assert pois[0]["district"] == "黄浦区"
    assert pois[0]["rating"] == 4.7
    assert pois[0]["avg_price"] == 128
    assert pois[0]["opening_hours_text"] == "11:00-22:00"
    expected_lat, expected_lng = gcj02_to_wgs84(31.23, 121.48)
    assert pois[0]["latitude"] == pytest.approx(expected_lat)
    assert pois[0]["longitude"] == pytest.approx(expected_lng)
    assert pois[0]["coord_system"] == "wgs84"
    assert pois[0]["provider_coord_system"] == "gcj02"


@pytest.mark.asyncio
async def test_amap_provider_uses_around_search_for_resolved_center():
    seen_path = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_path
        seen_path = request.url.path
        expected_lat, expected_lng = wgs84_to_gcj02(31.2304, 121.4737)
        assert request.url.params["location"] == f"{expected_lng:.6f},{expected_lat:.6f}"
        assert request.url.params["radius"] == "1800"
        return httpx.Response(200, json={"status": "1", "info": "OK", "pois": []})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://restapi.amap.com",
    )
    provider = AmapPoiProvider("test-key", client=client)
    try:
        assert await provider.fetch_for_plan(_plan(nearby=True)) == []
    finally:
        await client.aclose()
    assert seen_path == "/v3/place/around"


@pytest.mark.asyncio
async def test_amap_provider_uses_dynamic_city_for_text_search():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v3/place/text"
        assert request.url.params["city"] == "杭州市"
        assert request.url.params["citylimit"] == "true"
        return httpx.Response(200, json={"status": "1", "info": "OK", "pois": []})

    plan = RetrievalPlan(
        raw_query="杭州喝咖啡",
        filters=RetrievalFilters(city="杭州市"),
        domains=[DomainSpec(domain=IntentDomain.DINING, categories=["咖啡"])],
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://restapi.amap.com",
    ) as client:
        assert await AmapPoiProvider("test-key", client=client).fetch_for_plan(plan) == []


@pytest.mark.asyncio
async def test_amap_provider_surfaces_provider_error_without_key():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "0",
                "info": "DAILY_QUERY_OVER_LIMIT",
                "infocode": "10003",
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://restapi.amap.com",
    )
    provider = AmapPoiProvider("secret-test-key", client=client)
    try:
        with pytest.raises(AmapPoiProviderError) as error:
            await provider.fetch_for_plan(_plan())
    finally:
        await client.aclose()
    assert "DAILY_QUERY_OVER_LIMIT" in str(error.value)
    assert "secret-test-key" not in str(error.value)


@pytest.mark.asyncio
async def test_amap_provider_keeps_successful_batches_when_one_query_is_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        keyword = request.url.params.get("keywords")
        if keyword == "日料":
            return httpx.Response(
                200,
                json={"status": "0", "info": "CUQPS_HAS_EXCEEDED_THE_LIMIT", "infocode": "10020"},
            )
        return httpx.Response(
            200,
            json={
                "status": "1",
                "info": "OK",
                "infocode": "10000",
                "pois": [{
                    "id": "B002",
                    "name": "可用餐厅",
                    "type": "餐饮服务",
                    "location": "121.480000,31.230000",
                    "adname": "黄浦区",
                }],
            },
        )

    plan = RetrievalPlan(
        raw_query="黄浦区吃饭",
        filters=RetrievalFilters(district="黄浦区"),
        domains=[
            DomainSpec(
                domain=IntentDomain.DINING,
                categories=["日料", "西餐"],
            )
        ],
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://restapi.amap.com",
    ) as client:
        pois = await AmapPoiProvider("test-key", client=client).fetch_for_plan(plan)

    assert [poi["poi_id"] for poi in pois] == ["B002"]


@pytest.mark.asyncio
async def test_amap_provider_retries_transient_qps_limit_before_fallback():
    request_count = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            return httpx.Response(
                200,
                json={
                    "status": "0",
                    "info": "CUQPS_HAS_EXCEEDED_THE_LIMIT",
                    "infocode": "10021",
                },
            )
        return httpx.Response(
            200,
            json={
                "status": "1",
                "info": "OK",
                "infocode": "10000",
                "pois": [{
                    "id": "B003",
                    "name": "限流后可用景点",
                    "type": "风景名胜",
                    "location": "120.116000,30.225000",
                    "adname": "西湖区",
                }],
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://restapi.amap.com",
    ) as client:
        pois = await AmapPoiProvider(
            "test-key",
            client=client,
            max_retries=1,
            retry_base_seconds=0,
        ).fetch_for_plan(_plan(nearby=True))

    assert request_count == 2
    assert [poi["poi_id"] for poi in pois] == ["B003"]


@pytest.mark.asyncio
async def test_configured_amap_failure_falls_back_to_fixture(monkeypatch):
    async def failed_amap(_plan):
        raise AmapPoiProviderError("provider unavailable")

    async def unavailable_postgis(_database_url, _plan):
        return None, False

    monkeypatch.setattr(settings, "poi_provider", "amap")
    monkeypatch.setattr(poi_retrieval, "load_amap_pois", failed_amap)
    monkeypatch.setattr(poi_retrieval, "load_postgis_pois", unavailable_postgis)

    result, source, degraded, cache_hit = await poi_retrieval.retrieve_by_plan_async(_plan())

    assert source == "fixture"
    assert degraded is True
    assert cache_hit is False
    assert result.plan is not None


@pytest.mark.asyncio
async def test_amap_provider_honors_per_plan_query_limit_and_http_concurrency():
    request_count = 0
    inflight = 0
    peak_inflight = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal request_count, inflight, peak_inflight
        request_count += 1
        inflight += 1
        peak_inflight = max(peak_inflight, inflight)
        await asyncio.sleep(0.02)
        inflight -= 1
        return httpx.Response(200, json={"status": "1", "info": "OK", "pois": []})

    plan = RetrievalPlan(
        raw_query="多类餐饮",
        filters=RetrievalFilters(city="杭州市"),
        domains=[DomainSpec(
            domain=IntentDomain.DINING,
            categories=["日料", "西餐", "川菜", "粤菜", "火锅", "烧烤"],
        )],
        provider_query_limit=4,
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://restapi.amap.com",
    ) as client:
        await AmapPoiProvider("test-key", client=client, max_queries=8).fetch_for_plan(plan)

    assert request_count == 4
    assert peak_inflight == 2


@pytest.mark.asyncio
async def test_amap_provider_collapses_default_meal_categories_to_one_broad_query():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"status": "1", "info": "OK", "pois": []})

    plan = RetrievalPlan(
        raw_query="午餐",
        filters=RetrievalFilters(city="杭州市"),
        domains=[DomainSpec(
            domain=IntentDomain.DINING,
            categories=list(DEFAULT_MEAL_CATEGORIES),
        )],
        provider_query_limit=4,
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://restapi.amap.com",
    ) as client:
        await AmapPoiProvider("test-key", client=client, max_queries=8).fetch_for_plan(plan)

    assert len(requests) == 1
    assert requests[0].url.params["types"] == "050000"
    assert "keywords" not in requests[0].url.params
