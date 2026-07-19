"""Optional PostGIS-backed source for the existing POI retrieval pipeline."""

from __future__ import annotations

import json
from typing import Any

from ..config import settings


POI_CACHE_KEY = "gentrip:poi-source:v2"
POI_CACHE_TTL_SECONDS = 300


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

    async def fetch_all(self) -> list[dict]:
        pool = await self._get_pool()
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT poi_id, source, source_poi_id, name, category, district, business_area, address,
                           rating, price_per_person, queue_wait_min, is_open, raw,
                           ST_Y(location::geometry) AS lat, ST_X(location::geometry) AS lng
                    FROM pois WHERE is_open = TRUE
                    """
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


async def _load_cached_pois() -> list[dict] | None:
    if not settings.redis_url:
        return None
    try:
        import redis.asyncio as redis

        client = redis.from_url(settings.redis_url, decode_responses=True, protocol=2)
        try:
            raw = await client.get(POI_CACHE_KEY)
            return json.loads(raw) if raw else None
        finally:
            await client.aclose()
    except Exception:
        return None


async def _cache_pois(pois: list[dict]) -> None:
    if not settings.redis_url:
        return
    try:
        import redis.asyncio as redis

        client = redis.from_url(settings.redis_url, decode_responses=True, protocol=2)
        try:
            await client.set(POI_CACHE_KEY, json.dumps(pois, ensure_ascii=False), ex=POI_CACHE_TTL_SECONDS)
        finally:
            await client.aclose()
    except Exception:
        return


async def load_postgis_pois(database_url: str) -> tuple[list[dict] | None, bool]:
    """Return None when the optional data source is unavailable for deterministic fallback."""
    if not database_url:
        return None, False
    cached = await _load_cached_pois()
    if cached is not None:
        return cached, True
    try:
        pois = await PostgisPoiRepository(database_url).fetch_all()
        await _cache_pois(pois)
        return pois, False
    except Exception:
        return None, False
