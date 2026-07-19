from src.services.travel_time import MockTravelTimeEstimator
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
