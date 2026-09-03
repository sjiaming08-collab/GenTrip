"""TravelPlanner-to-GenTrip adaptation and benchmark aggregation.

This module builds a derived benchmark for GenTrip's single-city, day-route
scope. It deliberately does not implement or claim TravelPlanner's official
multi-day evaluation protocol.
"""

from __future__ import annotations

import ast
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Iterable


DISTRICTS = ("黄浦区", "徐汇区", "静安区", "浦东新区")
DISTRICT_ANCHORS = {
    "黄浦区": (31.2304, 121.4737),
    "徐汇区": (31.1883, 121.4365),
    "静安区": (31.2290, 121.4480),
    "浦东新区": (31.2350, 121.5050),
}
DAY_TO_DURATION_MIN = {3: 180, 5: 240, 7: 300}
CUISINE_MAP = {
    "Chinese": "本帮菜",
    "Italian": "西餐",
    "French": "西餐",
    "American": "西餐",
    "Mediterranean": "西餐",
    "Mexican": "西餐",
    "Indian": "西餐",
}
UNSUPPORTED_LOCAL_FIELDS = {
    "house rule": "accommodation_house_rule",
    "room type": "accommodation_room_type",
    "transportation": "intercity_transport_preference",
}


def _literal(value: str, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return fallback


def load_source_records(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_reference_records(path: Path) -> list[dict[str, Any]]:
    """Load the official per-query candidate catalog JSONL."""
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"reference row {line_number} must be an object")
            records.append(value)
    return records


def _reference_items(record: dict[str, Any], prefix: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for key, value in record.items():
        if key.startswith(prefix) and isinstance(value, list):
            result.extend(item for item in value if isinstance(item, dict))
    return result


def _local_coordinates(district: str, identity: str) -> tuple[float, float]:
    anchor_lat, anchor_lng = DISTRICT_ANCHORS[district]
    digest = hashlib.sha256(identity.encode()).digest()
    lat_offset = (int.from_bytes(digest[:2], "big") / 65535 - 0.5) * 0.012
    lng_offset = (int.from_bytes(digest[2:4], "big") / 65535 - 0.5) * 0.012
    return round(anchor_lat + lat_offset, 6), round(anchor_lng + lng_offset, 6)


def _attraction_category(name: str) -> str:
    lowered = name.casefold()
    if any(term in lowered for term in ("museum", "gallery", "art center", "arts center")):
        return "博物馆"
    if any(term in lowered for term in ("park", "garden", "trail", "nature", "zoo")):
        return "公园"
    if any(term in lowered for term in ("historic", "heritage", "memorial", "history")):
        return "文化"
    return "观光"


def _restaurant_category(cuisines: str, preferred: list[str], index: int) -> str:
    if preferred:
        return preferred[index % len(preferred)]
    lowered = cuisines.casefold()
    if any(term in lowered for term in ("japanese", "sushi")):
        return "日料"
    if any(term in lowered for term in ("chinese", "cantonese")):
        return "本帮菜"
    if any(term in lowered for term in ("cafe", "coffee", "tea")):
        return "咖啡"
    if any(term in lowered for term in ("fast food", "pizza", "burger")):
        return "小吃快餐"
    return "西餐"


def build_local_poi_fixture(
    cases: list[dict[str, Any]],
    references: list[dict[str, Any]],
    *,
    attractions_per_case: int = 8,
    restaurants_per_case: int = 10,
) -> dict[str, Any]:
    """Create an isolated local POI catalog from official candidate records.

    Source names and attributes are retained, while coordinates are explicitly
    transformed into deterministic Shanghai benchmark anchors. The result is
    evaluation data, not a claim that the source POIs exist in Shanghai.
    """
    pois: list[dict[str, Any]] = []
    for case in cases:
        source = case["source"]
        source_index = int(source["row_index"])
        if source_index >= len(references):
            raise ValueError(f"missing reference row {source_index} for {case['id']}")
        reference = references[source_index]
        mapping = case["adaptation"]["mapping"]
        district = str(mapping["district"])
        budget = int(mapping["budget_per_person"])
        preferred = [str(value) for value in mapping.get("preferred_cuisines") or []]

        attractions = _reference_items(reference, "Attractions in ")[:attractions_per_case]
        restaurants = _reference_items(reference, "Restaurants in ")[:restaurants_per_case]
        for kind, items in (("attraction", attractions), ("restaurant", restaurants)):
            for item_index, item in enumerate(items):
                name = str(item.get("Name") or f"{kind}-{item_index}")
                local_id = f"{case['id']}:{kind}:{item_index}"
                lat, lng = _local_coordinates(district, local_id)
                source_city = str(item.get("City") or source.get("destination") or "")
                if kind == "attraction":
                    category = _attraction_category(name)
                    price = min(40, max(0, budget // 5))
                    rating = 4.2 + (item_index % 5) * 0.1
                    duration = 55
                    opening = "09:00-21:00"
                else:
                    cuisines = str(item.get("Cuisines") or "")
                    category = _restaurant_category(cuisines, preferred, item_index)
                    raw_price = int(float(item.get("Average Cost") or 0))
                    price = min(max(raw_price, 35), max(35, int(budget * 0.75)))
                    rating = float(item.get("Aggregate Rating") or 4.0)
                    duration = 65
                    opening = "10:00-23:00"

                pois.append({
                    "poi_id": local_id,
                    "name": f"{name}（TravelPlanner评测）",
                    "source": "travelplanner_benchmark",
                    "category": "景点" if kind == "attraction" else "美食",
                    "sub_category": category,
                    "district": district,
                    "business_area": f"{district}TravelPlanner沙箱",
                    "address": str(item.get("Address") or f"{district}评测坐标"),
                    "location": {"lat": lat, "lng": lng},
                    "avg_price": price,
                    "rating": min(5.0, max(0.0, rating)),
                    "queue_minutes": 5,
                    "opening_hours_text": opening,
                    "opening_hours": [{"days": "Mon-Sun", "open": opening[:5], "close": opening[6:]}],
                    "recommended_duration_min": duration,
                    "openstatus": 1,
                    "status": "online",
                    "tags": ["benchmark_derived", f"source_city:{source_city}", f"case:{case['id']}"],
                    "data_tier": "benchmark_derived",
                    "field_provenance": {
                        "name": "travelplanner_reference",
                        "category": "gentrip_taxonomy_mapping",
                        "location": "deterministic_benchmark_transform",
                        "price": "travelplanner_reference_clamped_to_case_budget",
                    },
                    "benchmark_source": {
                        "benchmark": "TravelPlanner",
                        "split": source.get("split"),
                        "row_index": source_index,
                        "source_city": source_city,
                        "source_latitude": item.get("Latitude"),
                        "source_longitude": item.get("Longitude"),
                        "source_record": item,
                    },
                })

    return {
        "metadata": {
            "dataset": "TravelPlanner-derived-for-GenTrip",
            "protocol": "gentrip-derived-poi-v1",
            "evaluation_only": True,
            "coordinate_policy": "official attributes with deterministic Shanghai benchmark coordinates",
            "case_count": len(cases),
            "poi_count": len(pois),
        },
        "pois": pois,
    }


def _stable_district(split: str, source_index: int, destination: str) -> str:
    digest = hashlib.sha256(f"{split}:{source_index}:{destination}".encode()).digest()
    return DISTRICTS[int.from_bytes(digest[:2], "big") % len(DISTRICTS)]


def _normalized_budget(total_budget: int, people: int, days: int) -> int:
    daily_per_person = total_budget / max(people * days, 1)
    normalized = round((daily_per_person * 0.4) / 10) * 10
    return min(260, max(100, int(normalized)))


def _mapped_cuisines(local_constraints: dict[str, Any]) -> list[str]:
    raw = local_constraints.get("cuisine") or []
    if isinstance(raw, str):
        raw = [raw]
    return list(dict.fromkeys(CUISINE_MAP[item] for item in raw if item in CUISINE_MAP))


def adapt_record(record: dict[str, str], *, source_index: int, split: str) -> dict[str, Any]:
    """Adapt one official record into a transparent GenTrip-native case."""
    days = int(record.get("days") or 3)
    people = int(record.get("people_number") or 1)
    source_budget = int(float(record.get("budget") or 0))
    local_constraints = _literal(record.get("local_constraint", ""), {})
    if not isinstance(local_constraints, dict):
        local_constraints = {}

    district = _stable_district(split, source_index, record.get("dest", ""))
    duration_min = DAY_TO_DURATION_MIN.get(days, 240)
    budget_per_person = _normalized_budget(source_budget, people, days)
    cuisines = _mapped_cuisines(local_constraints)
    poi_count = 2 if duration_min <= 180 else 3 if duration_min <= 240 else 4

    query_parts = [
        f"请在{district}安排一条上海日内路线",
        f"{people}人出行，游玩{duration_min // 60}小时",
        f"人均预算不超过{budget_per_person}元",
        "包含观光和吃饭",
    ]
    if cuisines:
        query_parts.append(f"餐饮可选{'或'.join(cuisines)}")
    query_parts.append(f"尽量安排{poi_count}个活动")

    native_dimensions = ["budget", "attractions_and_meals"]
    if cuisines:
        native_dimensions.append("cuisine")
    adapted_dimensions = ["destination_to_district", "multi_day_to_day_duration"]
    unsupported_dimensions = ["group_size_state", "dated_inventory", "accommodation"]
    for source_name, normalized_name in UNSUPPORTED_LOCAL_FIELDS.items():
        if local_constraints.get(source_name) is not None:
            unsupported_dimensions.append(normalized_name)

    active_source_dimensions = 4 + sum(
        value is not None for value in local_constraints.values()
    )
    covered_dimensions = 3 + int(bool(cuisines))
    portable_coverage = round(covered_dimensions / max(active_source_dimensions, 1), 3)

    source_id = f"tp-{split}-{source_index:03d}"
    return {
        "id": source_id,
        "query": "，".join(query_parts) + "。",
        "source": {
            "benchmark": "TravelPlanner",
            "split": split,
            "row_index": source_index,
            "level": record.get("level"),
            "days": days,
            "origin": record.get("org"),
            "destination": record.get("dest"),
            "people_number": people,
            "budget": source_budget,
            "local_constraint": local_constraints,
            "query": record.get("query"),
        },
        "adaptation": {
            "protocol": "gentrip-derived-v1",
            "official_travelplanner_score": False,
            "native_dimensions": native_dimensions,
            "adapted_dimensions": adapted_dimensions,
            "unsupported_dimensions": unsupported_dimensions,
            "portable_constraint_coverage": portable_coverage,
            "mapping": {
                "district": district,
                "time_budget_minutes": duration_min,
                "budget_per_person": budget_per_person,
                "preferred_cuisines": cuisines,
                "poi_count": poi_count,
            },
        },
        "expect": {
            "must_complete": True,
            "must_be_legal": True,
            "must_satisfy_expectations": True,
            "required_domains": ["sightseeing", "dining"],
            "required_category_groups": [cuisines] if cuisines else [],
            "min_stops": poi_count,
            "min_quality_score": 0.72,
            "expected_constraints": {
                "district": district,
                "time_budget_minutes": duration_min,
                "budget_per_person": budget_per_person,
                "preferred_cuisines": cuisines,
                "domains": ["sightseeing", "dining"],
                "poi_count": poi_count,
            },
        },
    }


def select_balanced_records(
    records: list[dict[str, str]], *, samples_per_cell: int, seed: str
) -> list[tuple[int, dict[str, str]]]:
    """Select equal samples from each (difficulty, days) cell by stable hash."""
    grouped: dict[tuple[str, int], list[tuple[int, dict[str, str]]]] = defaultdict(list)
    for index, record in enumerate(records):
        grouped[(record.get("level", "unknown"), int(record.get("days") or 0))].append(
            (index, record)
        )

    selected: list[tuple[int, dict[str, str]]] = []
    for key in sorted(grouped):
        ranked = sorted(
            grouped[key],
            key=lambda item: hashlib.sha256(
                f"{seed}:{item[0]}:{item[1].get('query', '')}".encode()
            ).hexdigest(),
        )
        selected.extend(ranked[:samples_per_cell])
    return selected


def build_derived_cases(
    records: list[dict[str, str]], *, split: str, samples_per_cell: int = 2, seed: str = "gentrip-v1"
) -> list[dict[str, Any]]:
    selected = select_balanced_records(records, samples_per_cell=samples_per_cell, seed=seed)
    return [adapt_record(record, source_index=index, split=split) for index, record in selected]


def constraint_check(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    expected = ((case.get("expect") or {}).get("expected_constraints") or {})
    actual = result.get("constraints") or {}
    checks: list[dict[str, Any]] = []
    for field in ("district", "time_budget_minutes", "budget_per_person", "poi_count"):
        checks.append({"field": field, "passed": actual.get(field) == expected.get(field)})

    expected_domains = set(expected.get("domains") or [])
    actual_domains = set(actual.get("domains") or [])
    checks.append({"field": "domains", "passed": expected_domains.issubset(actual_domains)})

    expected_cuisines = set(expected.get("preferred_cuisines") or [])
    if expected_cuisines:
        actual_cuisines = set(actual.get("preferred_cuisines") or [])
        checks.append({
            "field": "preferred_cuisines",
            "passed": expected_cuisines.issubset(actual_cuisines),
        })

    passed = sum(bool(item["passed"]) for item in checks)
    return {
        "passed": passed,
        "total": len(checks),
        "score": round(passed / max(len(checks), 1), 3),
        "failed_fields": [item["field"] for item in checks if not item["passed"]],
    }


def _group_summary(items: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(items)
    if not rows:
        return {"cases": 0}
    return {
        "cases": len(rows),
        "completion_rate": round(mean(bool(item.get("is_completed")) for item in rows), 3),
        "legal_route_rate": round(mean(bool(item.get("is_legal")) for item in rows), 3),
        "route_case_pass_rate": round(mean(bool(item.get("route_case_passed")) for item in rows), 3),
        "end_to_end_pass_rate": round(mean(bool(item.get("passed")) for item in rows), 3),
        "mean_quality_score": round(mean(float(item.get("quality_score") or 0) for item in rows), 3),
        "constraint_macro_pass_rate": round(
            mean(float((item.get("constraint_check") or {}).get("score") or 0) for item in rows), 3
        ),
    }


def build_travelplanner_report(
    cases: list[dict[str, Any]], results: list[dict[str, Any]], *, live_llm: bool
) -> dict[str, Any]:
    by_id = {str(case["id"]): case for case in cases}
    enriched: list[dict[str, Any]] = []
    for result in results:
        case = by_id[str(result["id"])]
        check = constraint_check(case, result)
        route_case_passed = bool(result.get("passed"))
        enriched.append({
            **result,
            "passed": route_case_passed and check["passed"] == check["total"],
            "route_case_passed": route_case_passed,
            "source": case["source"],
            "adaptation": case["adaptation"],
            "constraint_check": check,
        })

    total_checks = sum(item["constraint_check"]["total"] for item in enriched)
    passed_checks = sum(item["constraint_check"]["passed"] for item in enriched)
    overall = _group_summary(enriched)
    overall.update({
        "constraint_micro_pass_rate": round(passed_checks / max(total_checks, 1), 3),
        "mean_portable_constraint_coverage": round(mean(
            float(item["adaptation"]["portable_constraint_coverage"]) for item in enriched
        ), 3) if enriched else 0.0,
        "mean_latency_ms": round(mean(float(item.get("runtime", {}).get("latency_ms") or 0) for item in enriched), 1) if enriched else 0.0,
        "total_tokens": sum(int(item.get("runtime", {}).get("token_usage", {}).get("total_tokens") or 0) for item in enriched),
    })

    by_level = {
        level: _group_summary(item for item in enriched if item["source"].get("level") == level)
        for level in ("easy", "medium", "hard")
    }
    by_days = {
        str(days): _group_summary(item for item in enriched if int(item["source"].get("days") or 0) == days)
        for days in (3, 5, 7)
    }
    return {
        "benchmark": "TravelPlanner-derived-for-GenTrip",
        "protocol_version": "gentrip-derived-v1",
        "official_travelplanner_score": None,
        "official_score_reason": "GenTrip does not yet produce the required multi-day transport, meal, and accommodation schema.",
        "live_llm": live_llm,
        "summary": overall,
        "by_level": by_level,
        "by_days": by_days,
        "cases": enriched,
    }
