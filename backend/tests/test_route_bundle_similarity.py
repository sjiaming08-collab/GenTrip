import pytest

from src.services.route_bundle_cache import RouteBundleCache


def _scored_route(stop_count: int = 3):
    stops = [
        {"poi_id": f"p-{index}", "poi_name": f"POI {index}", "category": "咖啡" if index == 0 else "观光"}
        for index in range(stop_count)
    ]
    return {"route": {"plan_id": "plan-1", "stops": stops}}


def _constraints(**overrides):
    value = {
        "district": "徐汇区",
        "domains": ["dining", "sightseeing"],
        "preferred_cuisines": ["咖啡"],
        "excluded_categories": [],
        "budget_per_person": 100,
        "time_budget_minutes": 180,
        "start_at": "14:00",
        "return_by": "18:00",
        "queue_tolerance_minutes": None,
        "poi_count": 3,
    }
    value.update(overrides)
    return value


@pytest.mark.asyncio
async def test_route_bundle_matches_nearby_budget_as_adapted_hot_path(monkeypatch):
    monkeypatch.setattr("src.services.route_bundle_cache.settings.redis_url", "")
    cache = RouteBundleCache(ttl_seconds=60)
    await cache.put(_constraints(), [_scored_route()])

    bundle = await cache.get(_constraints(budget_per_person=125))

    assert bundle is not None
    assert bundle.source == "local_similarity"
    assert 0.85 <= bundle.match_score < 1.0


@pytest.mark.asyncio
async def test_route_bundle_similarity_rejects_changed_hard_preferences(monkeypatch):
    monkeypatch.setattr("src.services.route_bundle_cache.settings.redis_url", "")
    cache = RouteBundleCache(ttl_seconds=60)
    await cache.put(_constraints(), [_scored_route()])

    changed_cuisine = await cache.get(_constraints(preferred_cuisines=["日料"]))
    changed_exclusion = await cache.get(_constraints(excluded_categories=["博物馆"]))

    assert changed_cuisine is None
    assert changed_exclusion is None


@pytest.mark.asyncio
async def test_route_bundle_rejects_different_or_shorter_stop_shape(monkeypatch):
    monkeypatch.setattr("src.services.route_bundle_cache.settings.redis_url", "")
    cache = RouteBundleCache(ttl_seconds=60)
    await cache.put(_constraints(), [_scored_route(stop_count=2)])

    assert await cache.get(_constraints()) is None
    assert await cache.get(_constraints(poi_count=4)) is None


@pytest.mark.asyncio
async def test_route_bundle_rejects_different_categories_within_same_domain(monkeypatch):
    monkeypatch.setattr("src.services.route_bundle_cache.settings.redis_url", "")
    cache = RouteBundleCache(ttl_seconds=60)
    massage = _constraints(
        raw_query="徐汇区做按摩，3小时，人均100元，安排3个地点",
        domains=["leisure"],
        preferred_cuisines=[],
    )
    route = {
        "route": {
            "plan_id": "massage-plan",
            "stops": [
                {"poi_id": f"m-{index}", "poi_name": f"按摩 {index}", "category": "按摩足疗"}
                for index in range(3)
            ],
        }
    }
    await cache.put(massage, [route])

    beauty = _constraints(
        raw_query="徐汇区做美容，3小时，人均100元，安排3个地点",
        domains=["leisure"],
        preferred_cuisines=[],
    )

    assert await cache.get(beauty) is None
