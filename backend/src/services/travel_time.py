"""Travel-time provider boundary with Amap routing and local fallback."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import httpx

from ..config import settings
from .coordinates import wgs84_to_gcj02


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


class AmapTravelTimeEstimator:
    """Estimate one route leg through Amap's walking or driving API."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://restapi.amap.com",
        timeout_sec: float = 5.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec
        self._client = client
        self._owned_client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        if self._owned_client is None:
            self._owned_client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout_sec,
            )
        return self._owned_client

    async def estimate(
        self,
        origin_lat: float,
        origin_lng: float,
        destination_lat: float,
        destination_lng: float,
        *,
        mode: str = "walking",
    ) -> TravelEstimate:
        if mode not in {"walking", "driving"}:
            raise ValueError(f"Amap travel mode is not supported: {mode}")
        origin_gcj_lat, origin_gcj_lng = wgs84_to_gcj02(origin_lat, origin_lng)
        destination_gcj_lat, destination_gcj_lng = wgs84_to_gcj02(destination_lat, destination_lng)
        client = await self._get_client()
        response = await client.get(
            f"/v3/direction/{mode}",
            params={
                "key": self.api_key,
                "origin": f"{origin_gcj_lng:.6f},{origin_gcj_lat:.6f}",
                "destination": f"{destination_gcj_lng:.6f},{destination_gcj_lat:.6f}",
                "output": "JSON",
            },
            timeout=self.timeout_sec,
        )
        response.raise_for_status()
        payload = response.json()
        if str(payload.get("status")) != "1":
            raise RuntimeError(str(payload.get("info") or "Amap route request failed"))
        route = payload.get("route") or {}
        paths = route.get("paths") or []
        if not paths:
            raise ValueError("Amap route response has no paths")
        path = paths[0]
        distance_m = int(path.get("distance") or route.get("distance") or 0)
        duration_sec = int(path.get("duration") or 0)
        if distance_m <= 0 or duration_sec <= 0:
            raise ValueError("Amap route response has invalid distance or duration")
        duration_min = max(1, math.ceil(duration_sec / 60))
        return TravelEstimate(
            distance_m=distance_m,
            duration_min=duration_min,
            min_duration_min=max(1, math.floor(duration_min * 0.9)),
            max_duration_min=max(duration_min, math.ceil(duration_min * 1.25)),
            confidence="high",
            source=f"amap_{mode}",
            estimated=False,
        )


class TravelTimeService:
    """Provider boundary for route timing; never lets a provider outage block planning."""

    def __init__(self, *, amap_estimator: AmapTravelTimeEstimator | None = None) -> None:
        self._amap_estimator = amap_estimator
        self._amap_signature: tuple[str, str, float] | None = None
        self._cache: dict[tuple, tuple[float, TravelEstimate]] = {}

    def _get_amap_estimator(self) -> AmapTravelTimeEstimator:
        if self._amap_estimator is not None:
            return self._amap_estimator
        signature = (settings.amap_api_key, settings.amap_base_url, settings.amap_timeout_sec)
        if self._amap_signature != signature:
            self._amap_estimator = AmapTravelTimeEstimator(
                settings.amap_api_key,
                base_url=settings.amap_base_url,
                timeout_sec=settings.amap_timeout_sec,
            )
            self._amap_signature = signature
        return self._amap_estimator

    @staticmethod
    def _cache_key(
        origin_lat: float,
        origin_lng: float,
        destination_lat: float,
        destination_lng: float,
        mode: str,
        provider: str,
    ) -> tuple:
        return (
            round(origin_lat, 5), round(origin_lng, 5),
            round(destination_lat, 5), round(destination_lng, 5), mode, provider,
        )

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
        provider = settings.travel_time_provider
        if provider == "mock":
            return fallback
        cache_key = self._cache_key(
            origin_lat, origin_lng, destination_lat, destination_lng, mode, provider
        )
        cached = self._cache.get(cache_key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        try:
            if provider == "amap":
                if not settings.amap_api_key:
                    raise ValueError("AMAP_API_KEY is not configured")
                estimate = await self._get_amap_estimator().estimate(
                    origin_lat,
                    origin_lng,
                    destination_lat,
                    destination_lng,
                    mode=mode,
                )
            elif provider == "http" and settings.travel_time_http_url:
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
                estimate = TravelEstimate(
                    distance_m=distance_m,
                    duration_min=duration_min,
                    min_duration_min=int(payload.get("min_duration_min") or duration_min),
                    max_duration_min=int(payload.get("max_duration_min") or duration_min),
                    confidence=str(payload.get("confidence") or "high"),
                    source=str(payload.get("source") or "http_provider"),
                    estimated=bool(payload.get("estimated", False)),
                )
            else:
                raise ValueError("travel-time provider is not configured")
            if len(self._cache) >= 2048:
                self._cache.clear()
            self._cache[cache_key] = (time.monotonic() + 900, estimate)
            return estimate
        except (httpx.HTTPError, KeyError, RuntimeError, TypeError, ValueError):
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
