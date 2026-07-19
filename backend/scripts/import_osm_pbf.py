#!/usr/bin/env python3
"""Import named OpenStreetMap POIs from a PBF extract into GenTrip PostGIS.

The importer preserves the OSM source and tags. It deliberately does not infer
ratings, prices, queues, or live opening state from OSM data.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import asyncpg
import osmium


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PBF = ROOT / "data" / "osm" / "shanghai-latest.osm.pbf"
GAZETTEER = Path(__file__).resolve().parents[1] / "fixtures" / "geo_gazetteer.json"
POI_CACHE_KEYS = ("gentrip:poi-source:fixture-v1", "gentrip:poi-source:v2")


@dataclass(frozen=True)
class DistrictScope:
    name: str
    lat: float
    lng: float
    radius_m: float


def _name(tags: dict[str, str]) -> str | None:
    for key in ("name:zh-Hans", "name:zh", "name", "brand:zh", "brand"):
        value = tags.get(key, "").strip()
        if value:
            return value
    return None


def _category(tags: dict[str, str]) -> str | None:
    amenity = tags.get("amenity")
    tourism = tags.get("tourism")
    leisure = tags.get("leisure")
    shop = tags.get("shop")
    cuisine = tags.get("cuisine", "").casefold()

    if amenity in {"restaurant", "fast_food", "food_court"}:
        if "japanese" in cuisine or "sushi" in cuisine:
            return "日料"
        if "sichuan" in cuisine:
            return "川菜"
        if "hotpot" in cuisine or "hot_pot" in cuisine:
            return "火锅"
        if any(word in cuisine for word in ("italian", "french", "western", "steak")):
            return "西餐"
        return "小吃快餐" if amenity != "restaurant" else "本帮菜"
    if amenity == "cafe" or shop == "coffee":
        return "咖啡"
    if amenity in {"ice_cream"} or shop in {"bakery", "confectionery"}:
        return "甜品"
    if amenity in {"bar", "pub", "biergarten"}:
        return "酒吧"
    if amenity in {"cinema", "theatre", "arts_centre", "nightclub"}:
        return "演出娱乐"
    if tourism == "museum":
        return "博物馆"
    if tourism in {"gallery", "artwork"}:
        return "文化艺术"
    if tourism in {"attraction", "viewpoint"}:
        return "观光"
    if tourism == "theme_park" or leisure in {"playground", "theme_park", "water_park"}:
        return "亲子游乐"
    if leisure == "park":
        return "公园"
    if leisure in {"fitness_centre", "sports_centre", "stadium", "swimming_pool", "pitch", "track"}:
        return "体育运动"
    if leisure in {"adult_gaming_centre", "escape_game"}:
        return "电玩游戏"
    if shop in {"mall", "department_store"}:
        return "商场"
    if shop in {"beauty", "hairdresser", "cosmetics"}:
        return "美容美体"
    if shop in {"massage", "spa"}:
        return "按摩足疗"
    return None


def _address(tags: dict[str, str]) -> str | None:
    if tags.get("addr:full"):
        return tags["addr:full"].strip()
    fields = [tags.get(key, "").strip() for key in ("addr:street", "addr:housenumber")]
    value = "".join(field for field in fields if field)
    return value or None


def _distance_m(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    earth_radius_m = 6_371_000
    d_lat = math.radians(b_lat - a_lat)
    d_lng = math.radians(b_lng - a_lng)
    x = math.sin(d_lat / 2) ** 2 + math.cos(math.radians(a_lat)) * math.cos(math.radians(b_lat)) * math.sin(d_lng / 2) ** 2
    return earth_radius_m * 2 * math.atan2(math.sqrt(x), math.sqrt(1 - x))


def _load_districts() -> list[DistrictScope]:
    entries = json.loads(GAZETTEER.read_text(encoding="utf-8"))
    return [
        DistrictScope(
            name=str(entry["district"]),
            lat=float(entry["center"]["lat"]),
            lng=float(entry["center"]["lng"]),
            radius_m=float(entry["radius_m"]),
        )
        for entry in entries
        if entry.get("place_type") == "district" and entry.get("district") and entry.get("center")
    ]


def _district(tags: dict[str, str], lat: float, lng: float, scopes: list[DistrictScope]) -> str | None:
    explicit = tags.get("addr:district", "").strip()
    if explicit:
        return explicit
    matches = [(scope, _distance_m(lat, lng, scope.lat, scope.lng)) for scope in scopes]
    valid = [(scope, distance) for scope, distance in matches if distance <= scope.radius_m]
    return min(valid, key=lambda item: item[1])[0].name if valid else None


def _coordinates(item: Any) -> tuple[float, float] | None:
    if item.type_str() == "n":
        return float(item.location.lat), float(item.location.lon)
    points = [(float(node.location.lat), float(node.location.lon)) for node in item.nodes if node.location.valid()]
    if not points:
        return None
    return sum(point[0] for point in points) / len(points), sum(point[1] for point in points) / len(points)


class PoiHandler(osmium.SimpleHandler):
    def __init__(self, *, limit: int | None) -> None:
        super().__init__()
        self.limit = limit
        self.districts = _load_districts()
        self.records: dict[str, dict[str, Any]] = {}

    def node(self, node: Any) -> None:
        self._add(node)

    def way(self, way: Any) -> None:
        self._add(way)

    def _add(self, item: Any) -> None:
        if self.limit is not None and len(self.records) >= self.limit:
            return
        tags = dict(item.tags)
        name = _name(tags)
        category = _category(tags)
        coordinates = _coordinates(item)
        if not name or not category or not coordinates:
            return
        lat, lng = coordinates
        source_id = f"{item.type_str()}/{item.id}"
        raw_tags = {key: value for key, value in tags.items() if key not in {"contact:phone", "phone"}}
        self.records[source_id] = {
            "source_id": source_id,
            "name": name,
            "category": category,
            "district": _district(tags, lat, lng, self.districts),
            "address": _address(tags),
            "lat": lat,
            "lng": lng,
            "raw": {
                "poi_id": source_id,
                "source": "osm",
                "source_poi_id": source_id,
                "name": name,
                "category": category,
                "categories": [category],
                "district": _district(tags, lat, lng, self.districts),
                "latitude": lat,
                "longitude": lng,
                "tags": ["openstreetmap", "osm_import"],
                "data_tier": "osm_import",
                "osm_tags": raw_tags,
                "osm_opening_hours": tags.get("opening_hours"),
                "license": "ODbL-1.0",
            },
        }


def parse_pbf(path: Path, *, limit: int | None) -> list[dict[str, Any]]:
    handler = PoiHandler(limit=limit)
    handler.apply_file(str(path), locations=True)
    return list(handler.records.values())


async def _invalidate_cache() -> None:
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
        return


async def import_records(records: list[dict[str, Any]], database_url: str) -> None:
    conn = await asyncpg.connect(database_url.replace("postgresql+asyncpg://", "postgresql://", 1))
    try:
        await conn.executemany(
            """
            INSERT INTO pois (
                poi_id, source, source_poi_id, name, category, district, address, location,
                rating, price_per_person, queue_wait_min, is_open, raw
            ) VALUES (
                $1, 'osm', $2, $3, $4, $5, $6,
                ST_SetSRID(ST_MakePoint($8, $7), 4326)::geography,
                0, 0, 0, TRUE, $9::jsonb
            )
            ON CONFLICT (source, source_poi_id) DO UPDATE SET
                name = EXCLUDED.name, category = EXCLUDED.category, district = EXCLUDED.district,
                address = EXCLUDED.address, location = EXCLUDED.location, raw = EXCLUDED.raw,
                updated_at = NOW()
            """,
            [
                (
                    f"osm:{record['source_id']}", record["source_id"], record["name"], record["category"],
                    record["district"], record["address"], record["lat"], record["lng"],
                    json.dumps(record["raw"], ensure_ascii=False),
                )
                for record in records
            ],
        )
        source_ids = [record["source_id"] for record in records]
        await conn.execute("DELETE FROM pois WHERE source = 'osm' AND NOT (source_poi_id = ANY($1::text[]))", source_ids)
        await _invalidate_cache()
    finally:
        await conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import named OSM POIs from a PBF into GenTrip PostGIS.")
    parser.add_argument("--input", type=Path, default=DEFAULT_PBF, help="Path to an OSM .pbf file.")
    parser.add_argument("--limit", type=int, help="Parse at most this many qualifying POIs.")
    parser.add_argument("--dry-run", action="store_true", help="Parse and report without changing PostGIS.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.input.is_file():
        raise SystemExit(f"OSM input not found: {args.input}")
    records = parse_pbf(args.input, limit=args.limit)
    print(f"parsed {len(records)} named OSM POIs")
    if args.dry_run:
        return 0
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        raise SystemExit("DATABASE_URL is required unless --dry-run is used")
    asyncio.run(import_records(records, database_url))
    print(f"imported {len(records)} OSM POIs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
