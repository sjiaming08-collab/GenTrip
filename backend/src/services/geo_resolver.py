"""Geo resolution for natural-language place mentions.

This module is intentionally not wired into the planning graph yet. It provides
a stable boundary for later integration: callers pass a user query and optional
location mentions, and receive a normalized GeoScope that POI retrieval can use.
"""

from __future__ import annotations

import asyncio
import json
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import httpx
from pydantic import BaseModel, Field

from ..models.constraints import Assumption

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"
GAZETTEER_PATH = FIXTURES_DIR / "geo_gazetteer.json"

DEFAULT_CITY = "上海"
DEFAULT_RADIUS_M = 1500
DEFAULT_DISTRICT = "徐汇区"


class GeoCandidate(BaseModel):
    name: str
    place_type: str = "place"
    district: str | None = None
    business_area: str | None = None
    address: str | None = None
    lat: float | None = None
    lng: float | None = None
    radius_m: int | None = None
    confidence: float = 0.0
    source: str
    provider_poi_id: str | None = None
    raw: dict = Field(default_factory=dict)


class GeoScope(BaseModel):
    raw_mentions: list[str] = Field(default_factory=list)
    resolved_name: str | None = None
    scope_type: str = "city"
    district: str | None = None
    business_area: str | None = None
    center_lat: float | None = None
    center_lng: float | None = None
    radius_m: int | None = None
    confidence: float = 0.0
    source: str = "none"
    assumptions: list[Assumption] = Field(default_factory=list)


class GeoProvider(Protocol):
    async def search_place(self, keyword: str, *, city: str = DEFAULT_CITY) -> list[GeoCandidate]:
        ...

    async def geocode(self, address: str, *, city: str = DEFAULT_CITY) -> list[GeoCandidate]:
        ...

    async def reverse_geocode(self, lat: float, lng: float) -> GeoCandidate | None:
        ...


@lru_cache
def load_gazetteer() -> list[dict]:
    with GAZETTEER_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _candidate_from_gazetteer(item: dict, *, confidence: float | None = None) -> GeoCandidate:
    center = item.get("center") or {}
    return GeoCandidate(
        name=item["name"],
        place_type=item.get("place_type") or "place",
        district=item.get("district"),
        business_area=item.get("business_area"),
        lat=center.get("lat"),
        lng=center.get("lng"),
        radius_m=item.get("radius_m"),
        confidence=confidence if confidence is not None else float(item.get("confidence") or 0.8),
        source="gazetteer",
        raw=item,
    )


class GazetteerGeoProvider:
    """Local gazetteer provider for deterministic tests and offline demos."""

    def __init__(self, entries: list[dict] | None = None) -> None:
        self.entries = entries if entries is not None else load_gazetteer()

    async def search_place(self, keyword: str, *, city: str = DEFAULT_CITY) -> list[GeoCandidate]:
        keyword = keyword.strip()
        if not keyword:
            return []

        candidates: list[GeoCandidate] = []
        for item in self.entries:
            names = [item["name"], *(item.get("aliases") or [])]
            if keyword in names:
                candidates.append(_candidate_from_gazetteer(item))
            elif any(keyword in name or name in keyword for name in names):
                confidence = max(0.0, float(item.get("confidence") or 0.8) - 0.08)
                candidates.append(_candidate_from_gazetteer(item, confidence=confidence))

        return sorted(candidates, key=lambda c: c.confidence, reverse=True)

    async def geocode(self, address: str, *, city: str = DEFAULT_CITY) -> list[GeoCandidate]:
        return await self.search_place(address, city=city)

    async def reverse_geocode(self, lat: float, lng: float) -> GeoCandidate | None:
        return None


class AmapGeoProvider:
    """Amap Web Service provider.

    It is optional and not used by the current graph. Tests should mock this
    provider instead of calling the network.
    """

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.AsyncClient | None = None,
        base_url: str = "https://restapi.amap.com",
        timeout_sec: float = 5.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec
        self._client = client

    async def _get(self, path: str, params: dict) -> dict:
        params = {**params, "key": self.api_key}
        if self._client is not None:
            response = await self._client.get(path, params=params, timeout=self.timeout_sec)
            response.raise_for_status()
            return response.json()

        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_sec) as client:
            response = await client.get(path, params=params)
            response.raise_for_status()
            return response.json()

    async def search_place(self, keyword: str, *, city: str = DEFAULT_CITY) -> list[GeoCandidate]:
        data = await self._get(
            "/v3/place/text",
            {
                "keywords": keyword,
                "city": city,
                "citylimit": "true",
                "offset": 10,
                "page": 1,
                "extensions": "base",
            },
        )
        pois = data.get("pois") or []
        candidates = []
        for idx, poi in enumerate(pois):
            location = _parse_amap_location(poi.get("location"))
            candidates.append(
                GeoCandidate(
                    name=poi.get("name") or keyword,
                    place_type="poi",
                    district=poi.get("adname"),
                    business_area=poi.get("business_area") or None,
                    address=poi.get("address") if isinstance(poi.get("address"), str) else None,
                    lat=location[0] if location else None,
                    lng=location[1] if location else None,
                    radius_m=DEFAULT_RADIUS_M,
                    confidence=max(0.55, 0.9 - idx * 0.04),
                    source="amap_place_search",
                    provider_poi_id=poi.get("id"),
                    raw=poi,
                )
            )
        return candidates

    async def geocode(self, address: str, *, city: str = DEFAULT_CITY) -> list[GeoCandidate]:
        data = await self._get(
            "/v3/geocode/geo",
            {
                "address": address,
                "city": city,
            },
        )
        geocodes = data.get("geocodes") or []
        candidates = []
        for idx, item in enumerate(geocodes):
            location = _parse_amap_location(item.get("location"))
            candidates.append(
                GeoCandidate(
                    name=item.get("formatted_address") or address,
                    place_type="address",
                    district=item.get("district") or None,
                    business_area=None,
                    address=item.get("formatted_address") or None,
                    lat=location[0] if location else None,
                    lng=location[1] if location else None,
                    radius_m=DEFAULT_RADIUS_M,
                    confidence=max(0.5, 0.86 - idx * 0.05),
                    source="amap_geocode",
                    raw=item,
                )
            )
        return candidates

    async def reverse_geocode(self, lat: float, lng: float) -> GeoCandidate | None:
        data = await self._get(
            "/v3/geocode/regeo",
            {
                "location": f"{lng},{lat}",
                "extensions": "base",
            },
        )
        regeocode = data.get("regeocode") or {}
        component = regeocode.get("addressComponent") or {}
        if not regeocode:
            return None
        return GeoCandidate(
            name=regeocode.get("formatted_address") or "当前位置",
            place_type="current_location",
            district=component.get("district") or None,
            business_area=None,
            address=regeocode.get("formatted_address") or None,
            lat=lat,
            lng=lng,
            radius_m=DEFAULT_RADIUS_M,
            confidence=0.9,
            source="amap_reverse_geocode",
            raw=regeocode,
        )


def _parse_amap_location(value: str | None) -> tuple[float, float] | None:
    if not value or "," not in value:
        return None
    lng_text, lat_text = value.split(",", 1)
    try:
        return float(lat_text), float(lng_text)
    except ValueError:
        return None


class GeoResolver:
    def __init__(
        self,
        providers: list[GeoProvider] | None = None,
        *,
        default_district: str = DEFAULT_DISTRICT,
        default_radius_m: int = DEFAULT_RADIUS_M,
    ) -> None:
        self.providers = providers if providers is not None else [GazetteerGeoProvider()]
        self.default_district = default_district
        self.default_radius_m = default_radius_m

    async def resolve_geo_scope(
        self,
        query: str,
        *,
        location_mentions: list[str] | None = None,
        user_lat: float | None = None,
        user_lng: float | None = None,
        city: str = DEFAULT_CITY,
    ) -> GeoScope:
        mentions = _dedupe_preserve_order(location_mentions or extract_location_mentions(query))

        if mentions:
            candidates = await self._resolve_mentions(mentions, city=city)
            if candidates:
                best = candidates[0]
                return self._scope_from_candidate(best, raw_mentions=mentions)

        if _nearby_requested(query) and user_lat is not None and user_lng is not None:
            candidate = await self._reverse_geocode(user_lat, user_lng)
            if candidate:
                return self._scope_from_candidate(candidate, raw_mentions=mentions)
            return GeoScope(
                raw_mentions=mentions,
                resolved_name="当前位置",
                scope_type="nearby",
                center_lat=user_lat,
                center_lng=user_lng,
                radius_m=self.default_radius_m,
                confidence=0.85,
                source="user_location",
            )

        assumption = Assumption(
            slot="district",
            assumed_value=self.default_district,
            source="geo_resolver_default",
            message=f"未识别到明确地点，默认推荐{self.default_district}",
        )
        return GeoScope(
            raw_mentions=mentions,
            resolved_name=self.default_district,
            scope_type="district",
            district=self.default_district,
            radius_m=None,
            confidence=0.3,
            source="default",
            assumptions=[assumption],
        )

    async def _resolve_mentions(self, mentions: list[str], *, city: str) -> list[GeoCandidate]:
        tasks = []
        for mention in mentions:
            for provider in self.providers:
                tasks.append(provider.search_place(mention, city=city))
                if _looks_like_address(mention):
                    tasks.append(provider.geocode(mention, city=city))
        if not tasks:
            return []

        results = await asyncio.gather(*tasks, return_exceptions=True)
        candidates: list[GeoCandidate] = []
        for result in results:
            if isinstance(result, Exception):
                continue
            candidates.extend(result)
        return sorted(candidates, key=lambda c: c.confidence, reverse=True)

    async def _reverse_geocode(self, lat: float, lng: float) -> GeoCandidate | None:
        tasks = [provider.reverse_geocode(lat, lng) for provider in self.providers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        candidates = [
            item
            for item in results
            if isinstance(item, GeoCandidate)
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda c: c.confidence, reverse=True)[0]

    def _scope_from_candidate(self, candidate: GeoCandidate, *, raw_mentions: list[str]) -> GeoScope:
        scope_type = candidate.place_type
        if candidate.business_area:
            scope_type = "business_area"
        elif candidate.district and not candidate.lat:
            scope_type = "district"
        elif candidate.lat is not None and candidate.lng is not None:
            scope_type = candidate.place_type or "place"

        return GeoScope(
            raw_mentions=raw_mentions,
            resolved_name=candidate.name,
            scope_type=scope_type,
            district=candidate.district,
            business_area=candidate.business_area,
            center_lat=candidate.lat,
            center_lng=candidate.lng,
            radius_m=candidate.radius_m,
            confidence=candidate.confidence,
            source=candidate.source,
        )


def extract_location_mentions(query: str) -> list[str]:
    """Small offline extractor based on gazetteer aliases.

    This is deliberately conservative. The future LLM constraint extractor can
    pass explicit location_mentions and bypass this helper.
    """

    aliases: list[str] = []
    for item in load_gazetteer():
        aliases.append(item["name"])
        aliases.extend(item.get("aliases") or [])
    aliases = sorted(set(aliases), key=len, reverse=True)

    mentions: list[str] = []
    covered_spans: list[tuple[int, int]] = []
    for alias in aliases:
        start = query.find(alias)
        if start < 0:
            continue
        end = start + len(alias)
        if any(not (end <= s or start >= e) for s, e in covered_spans):
            continue
        mentions.append(alias)
        covered_spans.append((start, end))
    return mentions


def _nearby_requested(query: str) -> bool:
    return any(word in query for word in ("附近", "周边", "离我近", "就近"))


def _looks_like_address(text: str) -> bool:
    return any(token in text for token in ("路", "街", "号", "弄", "广场", "中心"))


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        value = value.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
