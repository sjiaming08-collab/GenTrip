"""Amap Web Service POI provider normalized to GenTrip's local POI schema."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

import httpx

from ..config import settings
from ..models.constraints import IntentDomain
from ..models.retrieval import RetrievalPlan
from .category_taxonomy import DEFAULT_MEAL_CATEGORIES, all_retrieval_leaves, normalize_cuisine_term
from .coordinates import gcj02_to_wgs84, wgs84_to_gcj02


AMAP_POI_CACHE_PREFIX = "gentrip:amap-pois:v2"


class AmapPoiProviderError(RuntimeError):
    """Amap rejected a request or returned a malformed response."""


@dataclass(frozen=True)
class _SearchQuery:
    domain: IntentDomain
    keyword: str | None
    type_code: str
    requested_category: str | None = None


_DOMAIN_TYPE_CODES: dict[IntentDomain, tuple[str, ...]] = {
    IntentDomain.DINING: ("050000",),
    IntentDomain.SIGHTSEEING: ("110000",),
    IntentDomain.SHOPPING: ("060000",),
    IntentDomain.LEISURE: ("080000", "070000"),
}

_CATEGORY_RULES: tuple[tuple[str, str], ...] = (
    ("日本料理", "日料"), ("寿司", "日料"), ("火锅", "火锅"),
    ("咖啡", "咖啡"), ("甜品", "甜品"), ("蛋糕", "甜品"),
    ("烧烤", "烧烤"), ("川菜", "川菜"), ("粤菜", "粤菜"),
    ("上海菜", "本帮菜"), ("本帮", "本帮菜"), ("西餐", "西餐"),
    ("快餐", "小吃快餐"), ("小吃", "小吃快餐"), ("酒吧", "酒吧"),
    ("美术馆", "博物馆"), ("博物馆", "博物馆"),
    ("展览馆", "文化艺术"), ("文化馆", "文化艺术"),
    ("公园", "公园"), ("风景名胜", "观光"),
    ("购物中心", "商场"), ("商场", "商场"), ("百货", "购物"),
    ("按摩", "按摩足疗"), ("足疗", "按摩足疗"),
    ("美容", "美容美体"), ("美发", "美容美体"),
    ("健身", "体育运动"), ("体育", "体育运动"), ("游泳", "体育运动"),
    ("电玩", "电玩游戏"), ("游戏", "电玩游戏"),
    ("电影院", "演出娱乐"), ("剧场", "演出娱乐"),
    ("KTV", "演出娱乐"), ("儿童乐园", "亲子游乐"),
)

_DOMAIN_DEFAULT_CATEGORY = {
    IntentDomain.DINING: "小吃快餐",
    IntentDomain.SIGHTSEEING: "观光",
    IntentDomain.SHOPPING: "购物",
    IntentDomain.LEISURE: "演出娱乐",
}


def _search_queries(plan: RetrievalPlan, *, max_queries: int) -> list[_SearchQuery]:
    queries: list[_SearchQuery] = []
    seen: set[tuple[str, str, str]] = set()
    for spec in plan.domains:
        type_codes = _DOMAIN_TYPE_CODES[spec.domain]
        categories = list(spec.categories or [])
        broad_meal_query = (
            spec.domain == IntentDomain.DINING
            and set(categories) == set(DEFAULT_MEAL_CATEGORIES)
            and not spec.poi_names
            and not spec.search_keywords
        )
        keywords = [] if broad_meal_query else [
            *spec.poi_names,
            *categories,
            *spec.search_keywords,
        ]
        if keywords:
            for keyword in keywords:
                query = _SearchQuery(
                    domain=spec.domain,
                    keyword=keyword,
                    type_code=type_codes[0],
                    requested_category=keyword if keyword in (spec.categories or []) else None,
                )
                key = (query.domain.value, query.keyword or "", query.type_code)
                if key not in seen:
                    seen.add(key)
                    queries.append(query)
        else:
            for type_code in type_codes:
                query = _SearchQuery(spec.domain, None, type_code)
                key = (query.domain.value, "", query.type_code)
                if key not in seen:
                    seen.add(key)
                    queries.append(query)
    return queries[: max(1, max_queries)]


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return next((str(item).strip() for item in value if str(item).strip()), "")
    return ""


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _as_int(value: Any) -> int:
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def _parse_location(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, str) or "," not in value:
        return None
    lng_text, lat_text = value.split(",", 1)
    try:
        return float(lat_text), float(lng_text)
    except ValueError:
        return None


def _normalize_category(query: _SearchQuery, poi: dict[str, Any]) -> str:
    requested = normalize_cuisine_term(query.requested_category or "")
    if requested in all_retrieval_leaves():
        return requested
    haystack = " ".join(filter(None, (
        _as_text(poi.get("type")), _as_text(poi.get("tag")), _as_text(poi.get("name")),
    )))
    for marker, category in _CATEGORY_RULES:
        if marker.casefold() in haystack.casefold():
            return category
    return _DOMAIN_DEFAULT_CATEGORY[query.domain]


def _normalize_poi(poi: dict[str, Any], query: _SearchQuery) -> dict[str, Any] | None:
    gcj_location = _parse_location(poi.get("location"))
    poi_id = _as_text(poi.get("id"))
    name = _as_text(poi.get("name"))
    if not gcj_location or not poi_id or not name:
        return None
    location = gcj02_to_wgs84(*gcj_location)

    business = poi.get("business") if isinstance(poi.get("business"), dict) else {}
    biz_ext = poi.get("biz_ext") if isinstance(poi.get("biz_ext"), dict) else {}
    type_text = _as_text(poi.get("type"))
    category = _normalize_category(query, poi)
    opening_text = (
        _as_text(business.get("opentime_today"))
        or _as_text(business.get("opentime_week"))
        or _as_text(biz_ext.get("open_time"))
    )
    tags = [item.strip() for item in type_text.split(";") if item.strip()]
    tags.extend(["live_provider", "amap"])
    return {
        "poi_id": poi_id,
        "source": "amap",
        "name": name,
        "category": category,
        "sub_category": category,
        "categories": [category],
        "district": _as_text(poi.get("adname")),
        "business_area": _as_text(poi.get("business_area")),
        "address": _as_text(poi.get("address")),
        "latitude": location[0],
        "longitude": location[1],
        "coord_system": "wgs84",
        "provider_coord_system": "gcj02",
        "rating": _as_float(business.get("rating") or biz_ext.get("rating")),
        "avg_price": _as_int(business.get("cost") or biz_ext.get("cost")),
        "opening_hours": [],
        "opening_hours_text": opening_text or None,
        "queue_minutes": 0,
        "openstatus": 1,
        "status": "online",
        "data_tier": "live_provider",
        "tags": list(dict.fromkeys(tags)),
        "amap_typecode": _as_text(poi.get("typecode")),
    }


class AmapPoiProvider:
    """Bounded asynchronous Amap search client with injectable HTTP transport."""

    def __init__(self, api_key: str, *, base_url: str = "https://restapi.amap.com",
                 city: str = "上海", timeout_sec: float = 5.0, max_queries: int = 8,
                 min_request_interval_sec: float = 0.0, max_retries: int = 0,
                 retry_base_seconds: float = 0.0,
                 client: httpx.AsyncClient | None = None) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.city = city
        self.timeout_sec = timeout_sec
        self.max_queries = max_queries
        self.min_request_interval_sec = max(0.0, min_request_interval_sec)
        self.max_retries = max(0, max_retries)
        self.retry_base_seconds = max(0.0, retry_base_seconds)
        self._client = client
        self._owned_client: httpx.AsyncClient | None = None
        self._request_lock = asyncio.Lock()
        self._http_semaphore = asyncio.Semaphore(2)
        self._last_request_at = 0.0

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        if self._owned_client is None:
            self._owned_client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_sec)
        return self._owned_client

    async def close(self) -> None:
        if self._owned_client is not None:
            await self._owned_client.aclose()
            self._owned_client = None

    async def _get(self, path: str, params: dict[str, Any]) -> httpx.Response:
        """Pace request starts globally without serializing network latency."""
        async with self._request_lock:
            loop = asyncio.get_running_loop()
            wait_seconds = (
                self.min_request_interval_sec
                - (loop.time() - self._last_request_at)
            )
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
            self._last_request_at = loop.time()
        client = await self._get_client()
        async with self._http_semaphore:
            try:
                return await client.get(path, params=params, timeout=self.timeout_sec)
            finally:
                pass

    async def _search(self, query: _SearchQuery, plan: RetrievalPlan, *, offset: int) -> list[dict]:
        filters = plan.filters
        params: dict[str, Any] = {
            "key": self.api_key,
            "types": query.type_code,
            "offset": min(max(offset, 1), 25),
            "page": 1,
            "extensions": "all",
            "output": "JSON",
        }
        if query.keyword:
            params["keywords"] = query.keyword
        if filters.center_lat is not None and filters.center_lng is not None:
            path = "/v3/place/around"
            gcj_lat, gcj_lng = wgs84_to_gcj02(filters.center_lat, filters.center_lng)
            params.update({
                "location": f"{gcj_lng:.6f},{gcj_lat:.6f}",
                "radius": min(max(int(filters.radius_m or 3000), 100), 50000),
                "sortrule": "distance",
            })
        else:
            path = "/v3/place/text"
            params.update({
                "city": filters.district or filters.city or self.city,
                "citylimit": "true",
            })

        data: dict[str, Any] = {}
        retry_limit = 0 if plan.provider_query_limit is not None else self.max_retries
        for attempt in range(retry_limit + 1):
            response = await self._get(path, params)
            response.raise_for_status()
            data = response.json()
            if str(data.get("status")) == "1":
                break
            info = str(data.get("info") or "UNKNOWN_ERROR")
            infocode = str(data.get("infocode") or "")
            transient_qps_limit = (
                infocode in {"10020", "10021"}
                or info == "CUQPS_HAS_EXCEEDED_THE_LIMIT"
            )
            if transient_qps_limit and attempt < retry_limit:
                await asyncio.sleep(self.retry_base_seconds * (2 ** attempt))
                continue
            raise AmapPoiProviderError(f"Amap POI request failed: {info} ({infocode})")
        result: list[dict] = []
        for raw in data.get("pois") or []:
            if not isinstance(raw, dict):
                continue
            normalized = _normalize_poi(raw, query)
            if normalized is not None:
                result.append(normalized)
        return result

    async def fetch_for_plan(self, plan: RetrievalPlan, *, limit: int = 80) -> list[dict]:
        if not self.api_key:
            raise AmapPoiProviderError("AMAP_API_KEY is not configured")
        queries = _search_queries(
            plan,
            max_queries=min(self.max_queries, plan.provider_query_limit or self.max_queries),
        )
        if not queries:
            return []
        offset = max(8, min(25, (limit + len(queries) - 1) // len(queries)))
        async def guarded_search(query: _SearchQuery) -> list[dict]:
            return await self._search(query, plan, offset=offset)

        outcomes = await asyncio.gather(
            *(guarded_search(query) for query in queries),
            return_exceptions=True,
        )
        batches = [item for item in outcomes if isinstance(item, list)]
        if not batches:
            failure = next(
                (item for item in outcomes if isinstance(item, BaseException)),
                None,
            )
            if failure is not None:
                raise failure
        by_id: dict[str, dict] = {}
        for batch in batches:
            for poi in batch:
                by_id.setdefault(str(poi["poi_id"]), poi)
        return list(by_id.values())[:limit]


def _cache_key(plan: RetrievalPlan) -> str:
    encoded = json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{AMAP_POI_CACHE_PREFIX}:{sha256(encoded.encode('utf-8')).hexdigest()[:24]}"


async def _load_cache(key: str) -> list[dict] | None:
    if not settings.redis_url:
        return None
    try:
        import redis.asyncio as redis
        client = redis.from_url(settings.redis_url, decode_responses=True, protocol=2)
        try:
            raw = await client.get(key)
            return json.loads(raw) if raw else None
        finally:
            await client.aclose()
    except Exception:
        return None


async def _save_cache(key: str, pois: list[dict]) -> None:
    if not settings.redis_url:
        return
    try:
        import redis.asyncio as redis
        client = redis.from_url(settings.redis_url, decode_responses=True, protocol=2)
        try:
            await client.set(key, json.dumps(pois, ensure_ascii=False), ex=settings.amap_poi_cache_ttl_seconds)
        finally:
            await client.aclose()
    except Exception:
        return


_provider: AmapPoiProvider | None = None
_provider_signature: tuple[str, str, str, float, int, float, int, float] | None = None


def _configured_provider() -> AmapPoiProvider:
    global _provider, _provider_signature
    signature = (settings.amap_api_key, settings.amap_base_url, settings.amap_city,
                 settings.amap_timeout_sec, settings.amap_poi_max_queries,
                 settings.amap_min_request_interval_sec, settings.amap_max_retries,
                 settings.amap_retry_base_seconds)
    if _provider is None or signature != _provider_signature:
        _provider = AmapPoiProvider(
            settings.amap_api_key, base_url=settings.amap_base_url, city=settings.amap_city,
            timeout_sec=settings.amap_timeout_sec, max_queries=settings.amap_poi_max_queries,
            min_request_interval_sec=settings.amap_min_request_interval_sec,
            max_retries=settings.amap_max_retries,
            retry_base_seconds=settings.amap_retry_base_seconds,
        )
        _provider_signature = signature
    return _provider


async def load_amap_pois(plan: RetrievalPlan, *, limit: int = 80) -> tuple[list[dict], bool]:
    key = _cache_key(plan)
    cached = await _load_cache(key)
    if cached is not None:
        return cached, True
    pois = await _configured_provider().fetch_for_plan(plan, limit=limit)
    await _save_cache(key, pois)
    return pois, False


async def close_amap_poi_provider() -> None:
    global _provider, _provider_signature
    if _provider is not None:
        await _provider.close()
    _provider = None
    _provider_signature = None
