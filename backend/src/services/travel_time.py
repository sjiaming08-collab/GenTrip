"""Deterministic local travel-time estimate used until a routing provider is added."""

from __future__ import annotations

import math
from dataclasses import dataclass

import httpx

from ..config import settings


@dataclass(frozen=True)
class TravelEstimate:
    distance_m: int
    duration_min: int
    min_duration_min: int = 0
    max_duration_min: int = 0
    confidence: str = "medium"
    source: str = "mock_haversine"
    estimated: bool = True
    fallback_used: bool = False


class MockTravelTimeEstimator:
    """Deterministic local estimate with an explicit uncertainty interval."""

    _MODE_PARAMS = {
        "walking": (1.25, 4.5, 2),
        "cycling": (1.20, 12.0, 3),
        "driving": (1.38, 18.0, 5),
        "transit": (1.50, 15.0, 10),
        "mixed": (1.35, 12.0, 8),
    }

    def estimate(
        self,
        origin_lat: float,
        origin_lng: float,
        destination_lat: float,
        destination_lng: float,
        *,
        mode: str = "walking",
    ) -> TravelEstimate:
        radius = 6_371_000.0
        phi1, phi2 = math.radians(origin_lat), math.radians(destination_lat)
        d_phi, d_lng = math.radians(destination_lat - origin_lat), math.radians(destination_lng - origin_lng)
        h = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lng / 2) ** 2
        distance_m = int(round(2 * radius * math.atan2(math.sqrt(h), math.sqrt(1 - h))))
        detour_factor, speed_kmh, overhead_min = self._MODE_PARAMS.get(mode, self._MODE_PARAMS["mixed"])
        minutes = math.ceil((distance_m / 1000) * detour_factor / speed_kmh * 60 + overhead_min)
        expected = max(8, minutes)
        lower = max(1, math.floor(expected * 0.75))
        upper = max(expected, math.ceil(expected * 1.40))
        return TravelEstimate(
            distance_m=distance_m,
            duration_min=expected,
            min_duration_min=lower,
            max_duration_min=upper,
            confidence="medium",
            source="mock_haversine",
        )


mock_travel_estimator = MockTravelTimeEstimator()


class TravelTimeService:
    """Provider boundary for route timing; never lets a provider outage block planning."""

    async def estimate(
        self,
        origin_lat: float,
        origin_lng: float,
        destination_lat: float,
        destination_lng: float,
        *,
        mode: str = "walking",
    ) -> TravelEstimate:
        fallback = mock_travel_estimator.estimate(origin_lat, origin_lng, destination_lat, destination_lng, mode=mode)
        if settings.travel_time_provider != "http" or not settings.travel_time_http_url:
            return fallback
        try:
            async with httpx.AsyncClient(timeout=settings.travel_time_timeout_sec) as client:
                response = await client.get(
                    settings.travel_time_http_url,
                    params={"origin_lat": origin_lat, "origin_lng": origin_lng, "destination_lat": destination_lat, "destination_lng": destination_lng},
                )
                response.raise_for_status()
                payload = response.json()
            distance_m = int(payload["distance_m"])
            duration_min = int(payload["duration_min"])
            if distance_m < 0 or duration_min < 0:
                raise ValueError("negative travel estimate")
            return TravelEstimate(
                distance_m=distance_m,
                duration_min=duration_min,
                min_duration_min=int(payload.get("min_duration_min") or duration_min),
                max_duration_min=int(payload.get("max_duration_min") or duration_min),
                confidence=str(payload.get("confidence") or "high"),
                source=str(payload.get("source") or "http_provider"),
                estimated=bool(payload.get("estimated", False)),
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return TravelEstimate(
                distance_m=fallback.distance_m,
                duration_min=fallback.duration_min,
                min_duration_min=fallback.min_duration_min,
                max_duration_min=fallback.max_duration_min,
                confidence=fallback.confidence,
                source=fallback.source,
                estimated=True,
                fallback_used=True,
            )


travel_time_service = TravelTimeService()
