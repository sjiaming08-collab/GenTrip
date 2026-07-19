"""Idempotently import the local POI fixture into PostGIS."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import asyncpg


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "pois.json"
POI_CACHE_KEYS = ("gentrip:poi-source:fixture-v1", "gentrip:poi-source:v2")


def _location(poi: dict) -> tuple[float, float] | None:
    location = poi.get("location") or {}
    lat = poi.get("latitude", location.get("lat"))
    lng = poi.get("longitude", location.get("lng"))
    try:
        return float(lat), float(lng)
    except (TypeError, ValueError):
        return None


def _source_id(poi: dict, index: int) -> str:
    return str(poi.get("openshopid") or poi.get("poi_id") or poi.get("id") or index)


def _category(poi: dict) -> str:
    categories = poi.get("categories") or []
    return str(poi.get("sub_category") or poi.get("category") or (categories[0] if categories else "其他"))


async def _invalidate_poi_source_cache() -> None:
    redis_url = os.environ.get("REDIS_URL", "")
    if not redis_url:
        return
    try:
        import redis.asyncio as redis

        client = redis.from_url(redis_url, decode_responses=True, protocol=2)
        try:
            await client.delete(*POI_CACHE_KEYS)
        finally:
            await client.aclose()
    except Exception:
        # The database import is still valid when Redis is optional or unavailable.
        return


async def main() -> None:
    database_url = os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://", 1)
    if not database_url:
        raise SystemExit("DATABASE_URL is required")
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    pois = data.get("pois", []) if isinstance(data, dict) else data
    source_ids = [_source_id(poi, index) for index, poi in enumerate(pois)]
    conn = await asyncpg.connect(database_url)
    try:
        for index, poi in enumerate(pois):
            source_id = _source_id(poi, index)
            location = _location(poi)
            queue = poi.get("queue_minutes", 0)
            if isinstance(queue, dict):
                queue = queue.get("weekday", 0)
            await conn.execute(
                """
                INSERT INTO pois (
                    poi_id, source, source_poi_id, name, category, district, business_area,
                    address, location, rating, price_per_person, queue_wait_min, is_open, raw
                ) VALUES (
                    $1, 'fixture', $2, $3, $4, $5, $6, $7,
                    CASE WHEN $8::float8 IS NULL OR $9::float8 IS NULL THEN NULL
                         ELSE ST_SetSRID(ST_MakePoint($9, $8), 4326)::geography END,
                    $10, $11, $12, $13, $14::jsonb
                )
                ON CONFLICT (source, source_poi_id) DO UPDATE SET
                    name = EXCLUDED.name, category = EXCLUDED.category, district = EXCLUDED.district,
                    business_area = EXCLUDED.business_area, address = EXCLUDED.address,
                    location = EXCLUDED.location, rating = EXCLUDED.rating,
                    price_per_person = EXCLUDED.price_per_person, queue_wait_min = EXCLUDED.queue_wait_min,
                    is_open = EXCLUDED.is_open, raw = EXCLUDED.raw, updated_at = NOW()
                """,
                f"fixture:{source_id}", source_id, poi.get("name", "未知地点"), _category(poi),
                poi.get("district") or poi.get("area"), poi.get("business_area"), poi.get("address"),
                location[0] if location else None, location[1] if location else None,
                float(poi.get("star") or poi.get("rating") or 0), int(poi.get("avgprice") or poi.get("avg_price") or 0),
                int(queue or 0), bool(poi.get("openstatus", 1)) and poi.get("status", "online") != "closed",
                json.dumps(poi, ensure_ascii=False),
            )
        await conn.execute(
            "DELETE FROM pois WHERE source = 'fixture' AND NOT (source_poi_id = ANY($1::text[]))",
            source_ids,
        )
        await _invalidate_poi_source_cache()
        print(f"imported {len(pois)} POIs")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
