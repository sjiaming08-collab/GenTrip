"""Optional PostGIS-backed source for the existing POI retrieval pipeline."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from ..config import settings


POI_CACHE_KEY = "gentrip:poi-source:v3"
POI_CACHE_TTL_SECONDS = 300
POI_QUERY_LIMIT = 2000


def _scope_payload(plan: Any | None) -> dict[str, Any]:
    filters = getattr(plan, "filters", None)
    return {
        "district": getattr(filters, "district", None),
        "business_area": getattr(filters, "business_area", None),
        "center_lat": getattr(filters, "center_lat", None),
        "center_lng": getattr(filters, "center_lng", None),
        "radius_m": getattr(filters, "radius_m", None),
    }


def _scope_cache_key(plan: Any | None) -> str:
    scope = json.dumps(_scope_payload(plan), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{POI_CACHE_KEY}:{sha256(scope.encode('utf-8')).hexdigest()[:20]}"


class PostgisPoiRepository:
    """Loads normalized POIs from the local spatial store without changing ranking rules."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        self._pool: Any = None

    async def _get_pool(self) -> Any:
        if self._pool is None:
            import asyncpg

            self._pool = await asyncpg.create_pool(self.database_url, min_size=1, max_size=2)
        return self._pool

    async def fetch_for_plan(self, plan: Any | None = None, *, limit: int = POI_QUERY_LIMIT) -> list[dict]:
        scope = _scope_payload(plan)
        pool = await self._get_pool()
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT poi_id, source, source_poi_id, name, category, district, business_area, address,
                           opening_hours, recommended_duration_min, field_provenance,
                           rating, price_per_person, queue_wait_min, is_open, raw,
                           ST_Y(location::geometry) AS lat, ST_X(location::geometry) AS lng
                    FROM pois
                    WHERE is_open = TRUE
                    ORDER BY CASE
                        WHEN $1::text IS NOT NULL AND business_area = $1 THEN 0
                        WHEN $2::double precision IS NOT NULL AND $3::double precision IS NOT NULL
                             AND $4::integer IS NOT NULL AND location IS NOT NULL
                             AND ST_DWithin(
                                 location,
                                 ST_SetSRID(ST_MakePoint($3, $2), 4326)::geography,
                                 $4
                             ) THEN 1
                        WHEN $5::text IS NOT NULL AND district = $5 THEN 2
                        ELSE 3
                    END,
                    rating DESC NULLS LAST,
                    updated_at DESC
                    LIMIT $6
                    """,
                    scope["business_area"],
                    scope["center_lat"],
                    scope["center_lng"],
                    scope["radius_m"],
                    scope["district"],
                    min(max(int(limit), 1), POI_QUERY_LIMIT),
                )
        finally:
            await pool.close()
            self._pool = None
        result: list[dict] = []
        for row in rows:
            raw_value = row["raw"]
            raw = json.loads(raw_value) if isinstance(raw_value, str) else dict(raw_value or {})
            raw.update(
                {
                    "poi_id": row["source_poi_id"],
                    "source": row["source"],
                    "name": row["name"],
                    "category": row["category"],
                    "district": row["district"],
                    "business_area": row["business_area"],
                    "address": row["address"],
                    "opening_hours": row["opening_hours"],
                    "opening_hours_text": row["opening_hours"],
                    "recommended_duration_min": row["recommended_duration_min"],
                    "field_provenance": dict(row["field_provenance"] or {}),
                    "rating": row["rating"],
                    "avg_price": row["price_per_person"],
                    "queue_minutes": row["queue_wait_min"],
                    "openstatus": 1,
                    "status": "online",
                    "latitude": row["lat"],
                    "longitude": row["lng"],
                }
            )
            result.append(raw)
        return result

    async def fetch_all(self) -> list[dict]:
        """Compatibility entrypoint for import and diagnostics."""
        return await self.fetch_for_plan(None)


async def _load_cached_pois(cache_key: str) -> list[dict] | None:
    if not settings.redis_url:
        return None
    try:
        import redis.asyncio as redis

        client = redis.from_url(settings.redis_url, decode_responses=True, protocol=2)
        try:
            raw = await client.get(cache_key)
            return json.loads(raw) if raw else None
        finally:
            await client.aclose()
    except Exception:
        return None


async def _cache_pois(cache_key: str, pois: list[dict]) -> None:
    if not settings.redis_url:
        return
    try:
        import redis.asyncio as redis

        client = redis.from_url(settings.redis_url, decode_responses=True, protocol=2)
        try:
            await client.set(cache_key, json.dumps(pois, ensure_ascii=False), ex=POI_CACHE_TTL_SECONDS)
        finally:
            await client.aclose()
    except Exception:
        return


async def load_postgis_pois(database_url: str, plan: Any | None = None) -> tuple[list[dict] | None, bool]:
    """Return None when the optional data source is unavailable for deterministic fallback."""
    if not database_url:
        return None, False
    cache_key = _scope_cache_key(plan)
    cached = await _load_cached_pois(cache_key)
    if cached is not None:
        return cached, True
    try:
        pois = await PostgisPoiRepository(database_url).fetch_for_plan(plan)
        await _cache_pois(cache_key, pois)
        return pois, False
    except Exception:
        return None, False
