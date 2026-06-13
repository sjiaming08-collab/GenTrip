#!/usr/bin/env python3
"""从 OpenStreetMap Overpass API 拉取上海 POI，输出点评 Tier-1 字段格式。"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OUTPUT = Path(__file__).resolve().parents[1] / "fixtures" / "pois.json"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
TARGET_TOTAL = 1000
USER_AGENT = "GenTrip/0.1 (local route planning; contact: dev@local)"

# (district, south, west, north, east)
DISTRICT_BBOXES: list[tuple[str, float, float, float, float]] = [
    ("徐汇区", 31.162, 121.428, 31.215, 121.468),
    ("静安区", 31.218, 121.442, 31.238, 121.478),
    ("浦东新区", 31.152, 121.478, 31.255, 121.595),
    ("黄浦区", 31.215, 121.468, 31.245, 121.505),
]

PRICE_BY_CATEGORY: dict[str, int] = {
    "咖啡": 45,
    "甜品": 55,
    "小吃快餐": 35,
    "酒吧": 120,
    "本帮菜": 90,
    "川菜": 85,
    "日料": 150,
    "西餐": 180,
    "火锅": 110,
    "烧烤": 95,
    "博物馆": 30,
    "文化": 20,
    "观光": 0,
    "购物": 0,
    "公园": 0,
    "其他": 60,
}


def build_overpass_query(south: float, west: float, north: float, east: float) -> str:
    bbox = f"{south},{west},{north},{east}"
    return f"""
[out:json][timeout:180];
(
  nwr["name"]["amenity"~"restaurant|cafe|fast_food|bar|pub|food_court|ice_cream|biergarten"]({bbox});
  nwr["name"]["tourism"~"museum|gallery|attraction|viewpoint|theme_park"]({bbox});
  nwr["name"]["shop"~"mall|department_store|books|bakery|confectionery"]({bbox});
  nwr["name"]["leisure"~"park"]({bbox});
);
out center;
""".strip()


def fetch_overpass(query: str) -> dict:
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    req = urllib.request.Request(
        OVERPASS_URL,
        data=data,
        method="POST",
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=200) as resp:
        return json.loads(resp.read().decode("utf-8"))


def pick_name(tags: dict) -> str | None:
    for key in ("name:zh", "name:zh-CN", "name", "brand:zh", "brand"):
        value = tags.get(key, "").strip()
        if value:
            return value
    return None


def build_address(tags: dict, district: str) -> str:
    if full := tags.get("addr:full", "").strip():
        if district in full or "上海" in full:
            return full
        return f"上海市{district}{full}"
    parts = [
        tags.get("addr:street", ""),
        tags.get("addr:housenumber", ""),
    ]
    street = "".join(p for p in parts if p).strip()
    if street:
        return f"上海市{district}{street}"
    return f"上海市{district}"


def map_category(tags: dict) -> str:
    amenity = tags.get("amenity", "")
    shop = tags.get("shop", "")
    tourism = tags.get("tourism", "")
    leisure = tags.get("leisure", "")
    cuisine = tags.get("cuisine", "").lower()

    if amenity == "cafe" or shop == "coffee":
        return "咖啡"
    if amenity in ("ice_cream",) or shop in ("bakery", "confectionery"):
        return "甜品"
    if amenity in ("fast_food", "food_court"):
        return "小吃快餐"
    if amenity in ("bar", "pub", "biergarten"):
        return "酒吧"
    if tourism in ("museum", "gallery"):
        return "博物馆"
    if tourism in ("attraction", "viewpoint", "theme_park"):
        return "观光"
    if leisure == "park":
        return "公园"
    if shop in ("mall", "department_store"):
        return "购物"
    if shop == "books":
        return "文化"
    if "japanese" in cuisine or "sushi" in cuisine:
        return "日料"
    if any(k in cuisine for k in ("french", "italian", "western", "steak")):
        return "西餐"
    if "sichuan" in cuisine:
        return "川菜"
    if "hot_pot" in cuisine or "hotpot" in tags.get("name", "").lower():
        return "火锅"
    if amenity == "restaurant":
        return "本帮菜"
    return "其他"


def estimate_star(osm_id: int, category: str) -> float:
    base = {
        "博物馆": 4.5,
        "观光": 4.4,
        "公园": 4.3,
        "咖啡": 4.2,
        "本帮菜": 4.1,
    }.get(category, 4.0)
    jitter = (osm_id % 7) * 0.1
    return round(min(5.0, base + jitter), 1)


def estimate_price(category: str, osm_id: int) -> int:
    base = PRICE_BY_CATEGORY.get(category, 60)
    if base == 0:
        return 0
    return base + (osm_id % 5) * 5


def estimate_hours(tags: dict) -> str:
    hours = tags.get("opening_hours", "").strip()
    if hours and len(hours) <= 32 and "PH" not in hours:
        return hours.replace(" ", "")
    return "10:00-22:00"


def element_coords(element: dict) -> tuple[float, float] | None:
    if element["type"] == "node":
        return float(element["lat"]), float(element["lon"])
    center = element.get("center")
    if center:
        return float(center["lat"]), float(center["lon"])
    return None


def element_to_record(element: dict, district: str) -> dict | None:
    tags = element.get("tags") or {}
    name = pick_name(tags)
    if not name:
        return None
    coords = element_coords(element)
    if not coords:
        return None

    lat, lng = coords
    category = map_category(tags)
    osm_id = element["id"]
    el_type = element["type"][0]  # n/w/r

    return {
        "openshopid": f"osm_{el_type}{osm_id}",
        "openstatus": 1,
        "name": name,
        "branch_name": tags.get("branch", "").strip() or "",
        "city": "上海",
        "address": build_address(tags, district),
        "latitude": round(lat, 6),
        "longitude": round(lng, 6),
        "categories": [category],
        "star": estimate_star(osm_id, category),
        "avgprice": estimate_price(category, osm_id),
        "business_hour": estimate_hours(tags),
    }


def dedupe_key(record: dict) -> tuple:
    return (record["name"], round(record["latitude"], 4), round(record["longitude"], 4))


def fetch_district(
    district: str,
    south: float,
    west: float,
    north: float,
    east: float,
    limit: int,
) -> list[dict]:
    query = build_overpass_query(south, west, north, east)
    print(f"Fetching {district} ...")
    try:
        payload = fetch_overpass(query)
    except urllib.error.HTTPError as exc:
        print(f"  HTTP error {exc.code}, retry in 10s")
        time.sleep(10)
        payload = fetch_overpass(query)

    seen: set[tuple] = set()
    records: list[dict] = []
    for element in payload.get("elements", []):
        record = element_to_record(element, district)
        if not record:
            continue
        key = dedupe_key(record)
        if key in seen:
            continue
        seen.add(key)
        records.append(record)
        if len(records) >= limit:
            break

    print(f"  got {len(records)} POIs")
    return records


def main() -> None:
    per_district = TARGET_TOTAL // len(DISTRICT_BBOXES)
    all_records: list[dict] = []

    for idx, (district, south, west, north, east) in enumerate(DISTRICT_BBOXES):
        if idx > 0:
            time.sleep(5)
        all_records.extend(
            fetch_district(district, south, west, north, east, per_district + 50)
        )

    # 全局去重并截断
    seen: set[tuple] = set()
    unique: list[dict] = []
    for record in all_records:
        key = dedupe_key(record)
        if key in seen:
            continue
        seen.add(key)
        unique.append(record)
        if len(unique) >= TARGET_TOTAL:
            break

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8") as f:
        json.dump(unique, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"Wrote {len(unique)} records to {OUTPUT}")


if __name__ == "__main__":
    main()
