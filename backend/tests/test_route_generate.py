import pytest

from src.graph.nodes.route_generate import MAX_ROUTES, _derive_start_minute, route_generate
from src.models.route import RoutePlan


def _poi(idx: int, *, dimension: str, category: str, lat: float, lng: float, rating: float = 4.6, price: int = 80):
    return {
        "poi_id": f"poi_{idx}",
        "name": f"POI {idx}",
        "category": category,
        "district": "徐汇区",
        "lat": lat,
        "lng": lng,
        "rating": rating,
        "price_per_person": price,
        "composite_score": 1.0 - idx * 0.01,
        "dimension": dimension,
    }


def _state(
    pois: list[dict],
    *,
    domains: list[str],
    minutes: int = 240,
    raw_query: str = "测试路线",
    poi_count: int = 3,
    return_by: str | None = None,
):
    grouped: dict[str, list[dict]] = {}
    for poi in pois:
        grouped.setdefault(poi["dimension"], []).append(poi)
    constraints = {
        "raw_query": raw_query,
        "domains": domains,
        "district": "徐汇区",
        "budget_per_person": 120,
        "time_budget_minutes": minutes,
        "poi_count": poi_count,
    }
    if return_by:
        constraints["return_by"] = return_by
    return {
        "constraints": constraints,
        "geo_scope": {"resolved_name": "武康路-安福路"},
        "candidate_pois": pois,
        "candidate_pois_by_dim": grouped,
    }


def test_nearby_request_after_operating_window_uses_scene_default_time():
    state = {
        "user_query": "附近喝咖啡",
        "user_lat": 31.2,
        "user_lng": 121.4,
        "input_ts": "2026-07-16T23:15:00+08:00",
    }

    start = _derive_start_minute(state, {"raw_query": "附近喝咖啡", "domains": ["dining"]}, [])

    assert start == 14 * 60


@pytest.mark.asyncio
async def test_late_nearby_generation_discloses_default_start_assumption():
    state = _state(
        [_poi(1, dimension="dining", category="咖啡", lat=31.213, lng=121.436)],
        domains=["dining"],
        raw_query="附近喝咖啡",
        poi_count=1,
    )
    state.update({"user_query": "附近喝咖啡", "user_lat": 31.2, "user_lng": 121.4, "input_ts": "2026-07-16T23:15:00+08:00"})

    update = await route_generate(state)

    assert update["assumptions"][0]["slot"] == "start_at"
    assert update["assumptions"][0]["assumed_value"] == "14:00"


@pytest.mark.asyncio
async def test_route_generate_mixed_domains_uses_skeleton():
    pois = [
        _poi(1, dimension="sightseeing", category="博物馆", lat=31.213, lng=121.436),
        _poi(2, dimension="sightseeing", category="公园", lat=31.214, lng=121.437),
        _poi(3, dimension="dining", category="本帮菜", lat=31.215, lng=121.438),
        _poi(4, dimension="dining", category="咖啡", lat=31.216, lng=121.439),
    ]

    update = await route_generate(_state(pois, domains=["dining", "sightseeing"]))

    assert update["current_phase"] == "route_generate"
    assert 1 <= len(update["candidate_routes"]) <= MAX_ROUTES
    route = RoutePlan.model_validate(update["candidate_routes"][0])
    categories = {stop.category for stop in route.stops}
    assert categories & {"博物馆", "公园"}
    assert categories & {"本帮菜", "咖啡"}


@pytest.mark.asyncio
async def test_route_generate_caps_candidate_routes():
    pois = []
    for idx in range(12):
        dim = "dining" if idx % 2 else "sightseeing"
        cat = "本帮菜" if dim == "dining" else "博物馆"
        pois.append(_poi(idx + 1, dimension=dim, category=cat, lat=31.20 + idx * 0.001, lng=121.43 + idx * 0.001))

    update = await route_generate(_state(pois, domains=["dining", "sightseeing"]))

    assert len(update["candidate_routes"]) <= MAX_ROUTES


@pytest.mark.asyncio
async def test_route_generate_respects_small_time_budget_by_pruning():
    pois = [
        _poi(1, dimension="sightseeing", category="博物馆", lat=31.213, lng=121.436),
        _poi(2, dimension="sightseeing", category="公园", lat=31.214, lng=121.437),
        _poi(3, dimension="dining", category="本帮菜", lat=31.215, lng=121.438),
        _poi(4, dimension="dining", category="咖啡", lat=31.216, lng=121.439),
    ]

    update = await route_generate(_state(pois, domains=["dining", "sightseeing"], minutes=90))

    assert update["candidate_routes"]
    routes = [RoutePlan.model_validate(raw) for raw in update["candidate_routes"]]
    assert all(route.total_duration_min <= 108 for route in routes)
    assert update["route_generation_meta"]["pruned_by_time"] > 0


@pytest.mark.asyncio
async def test_route_generate_falls_back_when_requested_bucket_missing():
    pois = [
        _poi(1, dimension="dining", category="本帮菜", lat=31.213, lng=121.436),
        _poi(2, dimension="dining", category="咖啡", lat=31.214, lng=121.437),
    ]

    update = await route_generate(_state(pois, domains=["shopping", "dining"]))

    assert update["candidate_routes"]
    assert "route_generate_bucket_relaxed" in update.get("relaxed_constraints", [])
    assert update["route_generation_meta"]["used_fallback"] is True


@pytest.mark.asyncio
async def test_route_generate_prefers_mentioned_dining_categories_in_query_order():
    pois = [
        _poi(1, dimension="dining", category="本帮菜", lat=31.213, lng=121.436),
        _poi(2, dimension="dining", category="咖啡", lat=31.214, lng=121.437),
        _poi(3, dimension="dining", category="日料", lat=31.215, lng=121.438),
        _poi(4, dimension="dining", category="甜品", lat=31.216, lng=121.439),
    ]

    update = await route_generate(
        _state(
            pois,
            domains=["dining"],
            raw_query="徐家汇附近吃日料再喝咖啡",
            poi_count=2,
        )
    )

    route = RoutePlan.model_validate(update["candidate_routes"][0])
    assert [stop.category for stop in route.stops] == ["日料", "咖啡"]
    first_skeleton = update["route_generation_meta"]["skeletons"][0]
    assert [slot["categories"][0] for slot in first_skeleton] == ["日料", "咖啡"]


@pytest.mark.asyncio
async def test_route_generate_derives_start_time_from_return_by():
    pois = [
        _poi(1, dimension="dining", category="本帮菜", lat=31.213, lng=121.436),
        _poi(2, dimension="dining", category="咖啡", lat=31.214, lng=121.437),
    ]

    update = await route_generate(
        _state(
            pois,
            domains=["dining"],
            raw_query="晚上吃饭后喝咖啡，19:00 前回去",
            poi_count=2,
            return_by="19:00",
        )
    )

    route = RoutePlan.model_validate(update["candidate_routes"][0])
    assert update["route_generation_meta"]["start_time"] != "14:00"
    assert route.stops[-1].departure_time <= "19:00"


@pytest.mark.asyncio
async def test_route_generate_honors_explicit_afternoon_start_and_queue_wait():
    pois = [
        {**_poi(1, dimension="sightseeing", category="公园", lat=31.213, lng=121.436), "queue_wait_min": 20},
        {**_poi(2, dimension="sightseeing", category="博物馆", lat=31.214, lng=121.437), "queue_wait_min": 10},
    ]
    state = _state(pois, domains=["sightseeing"], raw_query="下午两点出发去玩", poi_count=2)
    state["constraints"]["start_at"] = "14:00"

    update = await route_generate(state)

    route = RoutePlan.model_validate(update["candidate_routes"][0])
    assert update["route_generation_meta"]["start_time"] == "14:00"
    assert route.stops[0].arrival_time == "14:00"
    assert sum(stop.queue_wait_min for stop in route.stops) == 30
    assert route.total_duration_min == 158


@pytest.mark.asyncio
async def test_route_generate_prunes_closed_pois_before_route_validation():
    pois = [
        {**_poi(1, dimension="dining", category="咖啡", lat=31.213, lng=121.436), "opening_hours": [{"open": "18:00", "close": "22:00"}]},
        {**_poi(2, dimension="dining", category="咖啡", lat=31.214, lng=121.437), "opening_hours": [{"open": "10:00", "close": "22:00"}]},
    ]
    state = _state(pois, domains=["dining"], poi_count=1)
    state["constraints"]["start_at"] = "14:00"

    update = await route_generate(state)

    route = RoutePlan.model_validate(update["candidate_routes"][0])
    assert route.stops[0].poi_id == "poi_2"
    assert update["route_generation_meta"]["pruned_by_hours"] > 0


@pytest.mark.asyncio
async def test_route_generate_shifts_assumed_start_to_opening_window():
    pois = [
        {
            **_poi(1, dimension="sightseeing", category="博物馆", lat=31.236, lng=121.503),
            "opening_hours": [{"days": "Mon-Sun", "open": "10:00", "close": "18:00"}],
        },
        {
            **_poi(2, dimension="sightseeing", category="观光", lat=31.237, lng=121.504),
            "opening_hours": [{"days": "Mon-Sun", "open": "10:30", "close": "20:00"}],
        },
    ]
    state = _state(pois, domains=["sightseeing"], raw_query="陆家嘴附近玩三个小时", poi_count=2, minutes=180)
    state["input_ts"] = "2026-07-18T09:00:00+08:00"

    update = await route_generate(state)

    assert update["candidate_routes"]
    route = RoutePlan.model_validate(update["candidate_routes"][0])
    assert route.stops[0].arrival_time >= "10:00"
    assert update["route_generation_meta"]["start_time_adjusted_for_hours"] is True


@pytest.mark.asyncio
async def test_route_generate_deduplicates_same_named_pois_with_different_ids():
    pois = [
        _poi(1, dimension="dining", category="咖啡", lat=31.213, lng=121.436),
        {**_poi(2, dimension="dining", category="咖啡", lat=31.214, lng=121.437), "name": "POI 1"},
        _poi(3, dimension="dining", category="咖啡", lat=31.215, lng=121.438),
    ]

    update = await route_generate(_state(pois, domains=["dining"], poi_count=2, minutes=180))

    assert update["candidate_routes"]
    for raw in update["candidate_routes"]:
        names = [stop["poi_name"] for stop in raw["stops"]]
        assert len(names) == len(set(names))


@pytest.mark.asyncio
async def test_route_generate_keeps_name_exact_candidate_when_bucket_is_full():
    pois = [
        {
            **_poi(1, dimension="dining", category="日料", lat=31.213, lng=121.436, rating=3.8),
            "name": "用户点名日料",
            "tags": ["match:name_exact"],
        }
    ]
    pois.extend(
        _poi(idx, dimension="dining", category="日料", lat=31.214 + idx * 0.001, lng=121.437, rating=5.0)
        for idx in range(2, 11)
    )

    update = await route_generate(_state(pois, domains=["dining"], raw_query="去用户点名日料", poi_count=1))

    first_route = RoutePlan.model_validate(update["candidate_routes"][0])
    assert first_route.stops[0].poi_name == "用户点名日料"
