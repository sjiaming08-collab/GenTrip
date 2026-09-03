from src.services.travel_time import AmapTravelTimeEstimator, MockTravelTimeEstimator
from src.services.travel_time import travel_time_service
from src.config import settings
import httpx
import pytest


def test_mock_travel_time_is_deterministic_and_has_existing_minimum() -> None:
    estimator = MockTravelTimeEstimator()

    first = estimator.estimate(31.213, 121.436, 31.214, 121.437)
    second = estimator.estimate(31.213, 121.436, 31.214, 121.437)

    assert first == second
    assert first.source == "mock_haversine"
    assert first.estimated is True
    assert first.duration_min >= 8


@pytest.mark.asyncio
async def test_http_provider_failure_falls_back_to_deterministic_estimate(monkeypatch) -> None:
    class FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, *_args, **_kwargs):
            raise httpx.ConnectError("routing unavailable")

    monkeypatch.setattr(settings, "travel_time_provider", "http")
    monkeypatch.setattr(settings, "travel_time_http_url", "http://routing.invalid/estimate")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: FailingClient())

    estimate = await travel_time_service.estimate(31.2, 121.4, 31.21, 121.41)

    assert estimate.source == "mock_haversine"
    assert estimate.estimated is True
    assert estimate.fallback_used is True


@pytest.mark.asyncio
async def test_amap_provider_returns_routed_distance_and_eta(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v3/direction/walking"
        assert request.url.params["origin"]
        assert request.url.params["destination"]
        return httpx.Response(200, json={
            "status": "1",
            "info": "OK",
            "route": {"paths": [{"distance": "1450", "duration": "780"}]},
        })

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://restapi.amap.com",
    ) as client:
        estimator = AmapTravelTimeEstimator("test-key", client=client)
        estimate = await estimator.estimate(31.2304, 121.4737, 31.2404, 121.4837)

    assert estimate.distance_m == 1450
    assert estimate.duration_min == 13
    assert estimate.source == "amap_walking"
    assert estimate.estimated is False
    assert estimate.confidence == "high"


@pytest.mark.asyncio
async def test_amap_provider_failure_falls_back(monkeypatch) -> None:
    monkeypatch.setattr(settings, "travel_time_provider", "amap")
    monkeypatch.setattr(settings, "amap_api_key", "test-key")

    class FailingEstimator:
        async def estimate(self, *_args, **_kwargs):
            raise httpx.ConnectError("Amap unavailable")

    from src.services.travel_time import TravelTimeService

    service = TravelTimeService(amap_estimator=FailingEstimator())
    estimate = await service.estimate(31.2, 121.4, 31.21, 121.41)

    assert estimate.source == "mock_haversine"
    assert estimate.fallback_used is True
