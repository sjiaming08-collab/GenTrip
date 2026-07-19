import pytest

from src.services.route_bundle_cache import RouteBundleCache


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
    await cache.put(_constraints(), [{"route": {"plan_id": "plan-1"}}])

    bundle = await cache.get(_constraints(budget_per_person=125))

    assert bundle is not None
    assert bundle.source == "local_similarity"
    assert 0.85 <= bundle.match_score < 1.0


@pytest.mark.asyncio
async def test_route_bundle_similarity_rejects_changed_hard_preferences(monkeypatch):
    monkeypatch.setattr("src.services.route_bundle_cache.settings.redis_url", "")
    cache = RouteBundleCache(ttl_seconds=60)
    await cache.put(_constraints(), [{"route": {"plan_id": "plan-1"}}])

    changed_cuisine = await cache.get(_constraints(preferred_cuisines=["日料"]))
    changed_exclusion = await cache.get(_constraints(excluded_categories=["博物馆"]))

    assert changed_cuisine is None
    assert changed_exclusion is None
