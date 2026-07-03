"""Fetch minimal POI seed data from OpenStreetMap Overpass API.

The output intentionally stays small: real name, category, area hint, location,
opening hours and source tags. Ratings, prices, queues and reviews are not OSM
facts, so they are left out for later enrichment.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from typing import Any


DEFAULT_ENDPOINT = "https://overpass-api.de/api/interpreter"
DEFAULT_SHANGHAI_CORE_BBOX = "31.16,121.38,31.27,121.52"


CATEGORY_TAGS = {
    "amenity": {
        "restaurant": "餐厅",
        "cafe": "咖啡厅",
        "fast_food": "快餐",
        "food_court": "美食广场",
        "bar": "酒吧",
        "pub": "酒馆",
        "ice_cream": "冰淇淋",
    },
    "tourism": {
        "attraction": "景点",
        "museum": "博物馆",
        "gallery": "美术馆",
    },
    "leisure": {
        "park": "公园",
        "fitness_centre": "健身",
        "sports_centre": "运动场馆",
    },
    "shop": {
        "bakery": "烘焙",
        "tea": "茶饮",
        "coffee": "咖啡零售",
    },
}


def build_query(bbox: str) -> str:
    selectors = [
        '["amenity"~"restaurant|cafe|fast_food|food_court|bar|pub|ice_cream"]',
        '["tourism"~"attraction|museum|gallery"]',
        '["leisure"~"park|fitness_centre|sports_centre"]',
        '["shop"~"bakery|tea|coffee"]',
    ]
    parts = []
    for selector in selectors:
        parts.append(f'node["name"]{selector}({bbox});')
        parts.append(f'way["name"]{selector}({bbox});')
        parts.append(f'relation["name"]{selector}({bbox});')
    joined = "\n  ".join(parts)
    return f"""[out:json][timeout:30];
(
  {joined}
);
out center tags;"""


def fetch_overpass(endpoint: str, query: str) -> dict[str, Any]:
    body = urllib.parse.urlencode({"data": query}).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={"User-Agent": "GenTripDemo/0.1 (synthetic seed builder)"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def category_from_tags(tags: dict[str, str]) -> str:
    for key, value_map in CATEGORY_TAGS.items():
        value = tags.get(key)
        if value in value_map:
            cuisine = tags.get("cuisine")
            if key == "amenity" and cuisine:
                return f"{value_map[value]}·{cuisine}"
            return value_map[value]
    return "POI"


def area_from_tags(tags: dict[str, str]) -> str:
    district = tags.get("addr:district") or tags.get("addr:subdistrict")
    street = tags.get("addr:street")
    if district and street:
        return f"{district}·{street}"
    if district:
        return district
    if street:
        return street
    return "上海"


def location_from_element(element: dict[str, Any]) -> dict[str, float] | None:
    if "lat" in element and "lon" in element:
        return {"lat": element["lat"], "lng": element["lon"]}
    center = element.get("center")
    if center and "lat" in center and "lon" in center:
        return {"lat": center["lat"], "lng": center["lon"]}
    return None


def tags_from_osm(tags: dict[str, str]) -> list[str]:
    result = []
    for key in ("cuisine", "amenity", "tourism", "leisure", "shop"):
        value = tags.get(key)
        if value:
            result.append(value)
    if tags.get("outdoor_seating") == "yes":
        result.append("outdoor_seating")
    if tags.get("takeaway") == "yes":
        result.append("takeaway")
    return result[:6]


def normalize(data: dict[str, Any], limit: int) -> dict[str, Any]:
    pois = []
    seen_names: set[str] = set()
    for element in data.get("elements", []):
        tags = element.get("tags") or {}
        name = tags.get("name")
        location = location_from_element(element)
        if not name or not location:
            continue
        if name in seen_names:
            continue
        seen_names.add(name)
        pois.append(
            {
                "id": f"osm_{element['type']}_{element['id']}",
                "name": name,
                "category": category_from_tags(tags),
                "area": area_from_tags(tags),
                "location": location,
                "open_hours": tags.get("opening_hours"),
                "tags": tags_from_osm(tags),
                "note": "Imported from OpenStreetMap. Price, rating and reviews require separate enrichment.",
                "source": {
                    "provider": "openstreetmap",
                    "osm_type": element["type"],
                    "osm_id": element["id"],
                },
            }
        )
        if len(pois) >= limit:
            break
    return {
        "schema_version": "poi_seed.v0.osm",
        "city": "上海",
        "source": "openstreetmap",
        "pois": pois,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument(
        "--bbox",
        default=DEFAULT_SHANGHAI_CORE_BBOX,
        help="south,west,north,east. Default covers central Shanghai.",
    )
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--output", default="data/poi_seed_osm_minimal.json")
    args = parser.parse_args()

    query = build_query(args.bbox)
    data = fetch_overpass(args.endpoint, query)
    output = normalize(data, args.limit)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"Wrote {len(output['pois'])} POIs to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
