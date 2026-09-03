"""[3] route_generate — controlled route generation from candidate POIs."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime

from ...config import settings
from ...models.blueprint import ItineraryBlueprint
from ...models.route import RouteLeg, RoutePlan, RouteStop, ScoredPoi
from ...services.travel_time import mock_travel_estimator
from ...services.planner_tools import TravelMatrixTool
from ...services.poi_hours import is_open_during, next_opening_start, weekday_from_date
from ...services.constraint_rules import (
    derive_minimum_poi_count,
    positive_domain_query,
    should_enforce_poi_count,
)
from ..state import GraphState, phase_update

BUCKET_LIMIT = 6
BEAM_WIDTH = 4
BLUEPRINT_BEAM_WIDTH = 12
MAX_SKELETONS = 3
MAX_ROUTES = 5
MAX_ROUTE_STOPS = 8
DEFAULT_START_MINUTE = 10 * 60

DINING_CATEGORIES = {"本帮菜", "火锅", "小吃快餐", "西餐", "日料", "咖啡", "甜品", "酒吧", "川菜", "粤菜", "烧烤"}
SHOPPING_CATEGORIES = {"购物", "商场", "百货"}
SHORT_STAY_CATEGORIES = {"咖啡", "甜品", "酒吧"}

CATEGORY_ALIASES: tuple[tuple[str, str], ...] = (
    ("日本料理", "日料"),
    ("寿司", "日料"),
    ("日料", "日料"),
    ("咖啡", "咖啡"),
    ("下午茶", "咖啡"),
    ("甜品", "甜品"),
    ("甜点", "甜品"),
    ("火锅", "火锅"),
    ("本帮", "本帮菜"),
    ("上海菜", "本帮菜"),
    ("西餐", "西餐"),
    ("川菜", "川菜"),
    ("粤菜", "粤菜"),
    ("烧烤", "烧烤"),
    ("小吃", "小吃快餐"),
)


@dataclass(frozen=True)
class SlotHint:
    domain: str
    categories: tuple[str, ...] = ()
    avoid_categories: tuple[str, ...] = ()
    note: str | None = None


@dataclass(frozen=True)
class BeamCandidate:
    pois: tuple[ScoredPoi, ...]
    duration_min: int
    estimated_cost_per_person: int
    score: float


@dataclass(frozen=True)
class ScheduledBeam:
    pois: tuple[ScoredPoi, ...]
    legs: tuple[RouteLeg, ...]
    start_minute: int
    cursor_minute: int
    estimated_cost_per_person: int
    score: float


@dataclass
class GenerationStats:
    used_fallback: bool = False
    pruned_by_time: int = 0
    pruned_by_budget: int = 0
    pruned_by_queue: int = 0


def _select_blueprint_beams(
    candidates: list[BeamCandidate],
    limit: int = BLUEPRINT_BEAM_WIDTH,
) -> list[BeamCandidate]:
    """Keep high-scoring beams without discarding all compact alternatives."""
    ranked = sorted(
        candidates,
        key=lambda item: (-item.score, tuple(poi.poi_id for poi in item.pois)),
    )
    selected: list[BeamCandidate] = []
    selected_ids: set[int] = set()
    seen_counts: set[int] = set()
    for item in ranked:
        count = len(item.pois)
        if count in seen_counts:
            continue
        selected.append(item)
        selected_ids.add(id(item))
        seen_counts.add(count)
        if len(selected) >= limit:
            return selected
    for item in ranked:
        if id(item) in selected_ids:
            continue
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def _domain_of_poi(poi: ScoredPoi) -> str:
    if poi.dimension:
        return poi.dimension
    if poi.category in DINING_CATEGORIES:
        return "dining"
    if poi.category in SHOPPING_CATEGORIES:
        return "shopping"
    return "sightseeing"


def _visit_duration(poi: ScoredPoi, cap_minutes: int | None = None) -> int:
    if poi.slot_duration_minutes:
        base = int(poi.slot_duration_minutes)
        return min(base, cap_minutes) if cap_minutes is not None else base
    domain = _domain_of_poi(poi)
    if poi.category in SHORT_STAY_CATEGORIES:
        base = 45
    elif domain == "dining":
        base = 75
    else:
        base = 60
    return min(base, cap_minutes) if cap_minutes is not None else base


def _dense_visit_cap(poi_count: int, time_budget_minutes: int | None) -> int | None:
    """Reserve travel and queue time before distributing dense-plan visit time."""
    if poi_count < 4 or not time_budget_minutes:
        return None
    travel_reserve = max(0, poi_count - 1) * 10
    queue_reserve = poi_count * 5
    available = int(time_budget_minutes) - travel_reserve - queue_reserve
    return max(40, available // poi_count)


def _queue_wait_min(poi: ScoredPoi) -> int:
    return max(0, int(poi.queue_wait_min))


def _distance_m(a: ScoredPoi, b: ScoredPoi) -> float:
    radius = 6371000.0
    phi1 = math.radians(a.lat)
    phi2 = math.radians(b.lat)
    d_phi = math.radians(b.lat - a.lat)
    d_lambda = math.radians(b.lng - a.lng)
    h = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def _travel_time_min(prev: ScoredPoi | None, current: ScoredPoi) -> int:
    if prev is None:
        return 0
    return mock_travel_estimator.estimate(prev.lat, prev.lng, current.lat, current.lng).duration_min


def _poi_quality(poi: ScoredPoi) -> float:
    name_exact_bonus = 3.0 if "match:name_exact" in poi.tags else 0.0
    return poi.composite_score + poi.rating / 5 + name_exact_bonus


def _normalized_poi_name(name: str) -> str:
    return "".join(name.casefold().split())


def _dedupe_pois_by_name(pois: list[ScoredPoi]) -> list[ScoredPoi]:
    result: list[ScoredPoi] = []
    seen: set[str] = set()
    for poi in pois:
        key = _normalized_poi_name(poi.name)
        if key in seen:
            continue
        seen.add(key)
        result.append(poi)
    return result


def _group_pois(pois: list[ScoredPoi]) -> dict[str, list[ScoredPoi]]:
    buckets: dict[str, list[ScoredPoi]] = {}
    seen_by_bucket: dict[str, set[str]] = {}
    for poi in pois:
        key = _domain_of_poi(poi)
        seen = seen_by_bucket.setdefault(key, set())
        if poi.poi_id in seen:
            continue
        seen.add(poi.poi_id)
        buckets.setdefault(key, []).append(poi)

    for key, items in buckets.items():
        ranked = sorted(items, key=_poi_quality, reverse=True)
        pinned = [poi for poi in ranked if "match:name_exact" in poi.tags]
        regular = [poi for poi in ranked if "match:name_exact" not in poi.tags]
        representatives: list[ScoredPoi] = []
        represented_categories: set[str] = set()
        for poi in regular:
            if poi.category not in represented_categories:
                representatives.append(poi)
                represented_categories.add(poi.category)
        buckets[key] = _dedupe_pois_by_name(
            pinned + representatives + regular
        )[: BUCKET_LIMIT * 2]
    return buckets


def _ordered_domains(raw_domains: list[str] | None) -> list[str]:
    result: list[str] = []
    for domain in raw_domains or []:
        if domain not in result:
            result.append(domain)
    return result or ["sightseeing"]


def _slot(domain: str, categories: tuple[str, ...] = (), note: str | None = None) -> SlotHint:
    return SlotHint(domain=domain, categories=categories, note=note)


def _mentioned_categories(query: str) -> list[str]:
    query = positive_domain_query(query)
    hits: list[tuple[int, str]] = []
    for needle, category in CATEGORY_ALIASES:
        pos = query.find(needle)
        if pos >= 0:
            hits.append((pos, category))

    ordered: list[str] = []
    for _, category in sorted(hits, key=lambda item: item[0]):
        if category not in ordered:
            ordered.append(category)
    return ordered


def _explicit_mixed_skeleton(domains: list[str], categories: list[str], query: str) -> list[SlotHint]:
    """Keep explicit cuisine slots while preserving the user's activity order."""
    first_positions = {
        "dining": min((query.find(category) for category in categories if category in query), default=len(query)),
        "sightseeing": min(
            (query.find(term) for term in ("看展", "艺术展", "画廊", "艺术空间", "展览", "散步", "公园", "景点", "博物馆", "观光", "打卡") if term in query),
            default=len(query),
        ),
        "shopping": min(
            (query.find(term) for term in ("逛街", "商场", "购物", "书店", "买手店", "古着") if term in query),
            default=len(query),
        ),
        "leisure": min(
            (
                query.find(term)
                for term in (
                    "按摩", "足疗", "推拿", "美容", "美甲", "健身", "攀岩",
                    "游泳", "羽毛球", "电玩", "桌游", "演出", "电影院", "KTV",
                    "亲子", "儿童乐园",
                )
                if term in query
            ),
            default=len(query),
        ),
    }
    ordered_domains = sorted(domains, key=lambda domain: (first_positions.get(domain, len(query)), domains.index(domain)))
    slots: list[SlotHint] = []
    for domain in ordered_domains:
        if domain == "dining":
            if len(categories) > 1 and "或" in query:
                slots.append(_slot("dining", tuple(categories), "或".join(categories)))
            else:
                slots.extend(_slot("dining", (category,), category) for category in categories)
        elif domain == "sightseeing" and any(term in query for term in ("看展", "展览", "博物馆", "美术馆")):
            category = "博物馆" if any(term in query for term in ("展览", "博物馆", "美术馆")) else "文化艺术"
            slots.append(_slot("sightseeing", (category,), category))
        else:
            slots.append(_slot(domain))
    return slots


def _trim_skeleton(items: list[SlotHint], poi_count: int) -> list[SlotHint]:
    target = max(1, min(poi_count, MAX_ROUTE_STOPS))
    return items[:target]


def _has_explicit_activity_count(query: str) -> bool:
    return bool(re.search(r"(?:\d{1,2}|[一二两三四五六七八九十]+)\s*个?\s*(?:活动|地点|景点|去处|项目|站)", query))


def _alternating_slots(first: str, second: str, target: int) -> list[SlotHint]:
    return [_slot(first if index % 2 == 0 else second) for index in range(target)]


def _pad_explicit_skeleton(
    skeleton: list[SlotHint],
    domains: list[str],
    poi_count: int,
    query: str,
    *,
    enforce_target: bool = False,
) -> list[SlotHint]:
    if not enforce_target and not _has_explicit_activity_count(query):
        return skeleton
    target = max(1, min(poi_count, MAX_ROUTE_STOPS))
    padded = list(skeleton)
    cursor = 0
    while len(padded) < target:
        domain = domains[cursor % len(domains)] if domains else "sightseeing"
        padded.append(_slot(domain))
        cursor += 1
    return padded


def _route_skeletons(
    domains: list[str],
    poi_count: int,
    query: str = "",
    *,
    minimum_stop_count: int | None = None,
) -> list[list[SlotHint]]:
    domain_set = set(domains)
    skeletons: list[list[SlotHint]] = []
    mentioned_categories = _mentioned_categories(query)
    enforce_target = should_enforce_poi_count(query)
    compact_target = max(
        1,
        min(
            int(minimum_stop_count or min(poi_count, 2)),
            poi_count,
            MAX_ROUTE_STOPS,
        ),
    )

    if mentioned_categories and "dining" in domain_set:
        explicit_slots = [_slot("dining", (category,), category) for category in mentioned_categories]
        explicit_skeleton = (
            _explicit_mixed_skeleton(domains, mentioned_categories, query)
            if len(domain_set) > 1
            else explicit_slots
        )
        skeletons.append(
            _pad_explicit_skeleton(
                explicit_skeleton,
                domains,
                poi_count,
                query,
                enforce_target=enforce_target,
            )
        )

    if {"dining", "sightseeing"}.issubset(domain_set):
        target = max(2, min(poi_count, MAX_ROUTE_STOPS))
        skeletons.append(_alternating_slots("sightseeing", "dining", target))
        if not enforce_target:
            skeletons.append(_alternating_slots("sightseeing", "dining", compact_target))
        skeletons.append(_alternating_slots("dining", "sightseeing", target))
    elif {"shopping", "dining"}.issubset(domain_set):
        target = max(2, min(poi_count, MAX_ROUTE_STOPS))
        skeletons.append(_alternating_slots("shopping", "dining", target))
        if not enforce_target:
            skeletons.append(_alternating_slots("shopping", "dining", compact_target))
        skeletons.append(_alternating_slots("dining", "shopping", target))
    elif domains == ["dining"]:
        target = max(1, min(poi_count, MAX_ROUTE_STOPS))
        skeletons.append([_slot("dining") for _ in range(target)])
        if not enforce_target:
            skeletons.append([_slot("dining") for _ in range(compact_target)])
    elif domains == ["sightseeing"]:
        skeletons.append(
            [_slot("sightseeing") for _ in range(max(1, min(poi_count, MAX_ROUTE_STOPS)))]
        )
        if not enforce_target:
            skeletons.append(
                [_slot("sightseeing") for _ in range(compact_target)]
            )
    elif domains == ["shopping"]:
        skeletons.append(
            [_slot("shopping") for _ in range(max(1, min(poi_count, MAX_ROUTE_STOPS)))]
        )
        if not enforce_target:
            skeletons.append([_slot("shopping") for _ in range(compact_target)])
    else:
        mixed: list[SlotHint] = []
        target = max(1, min(poi_count, MAX_ROUTE_STOPS))
        while len(mixed) < target:
            mixed.extend(_slot(domain) for domain in domains)
        skeletons.append(mixed[:target])
        if not enforce_target:
            compact: list[SlotHint] = []
            while len(compact) < compact_target:
                compact.extend(_slot(domain) for domain in domains)
            skeletons.append(compact[:compact_target])

    deduped: list[list[SlotHint]] = []
    for skeleton in skeletons:
        trimmed = _trim_skeleton(skeleton, poi_count)
        if trimmed and trimmed not in deduped:
            deduped.append(trimmed)
    return deduped[:MAX_SKELETONS]


def _avg_cost(pois: tuple[ScoredPoi, ...]) -> int:
    paid = [p.price_per_person for p in pois if p.price_per_person > 0]
    return int(sum(paid) / len(paid)) if paid else 0


def _candidate_pool(slot: SlotHint, buckets: dict[str, list[ScoredPoi]], all_pois: list[ScoredPoi]) -> tuple[list[ScoredPoi], bool]:
    domain_pool = buckets.get(slot.domain) or []
    allowed = set(slot.categories)
    avoided = set(slot.avoid_categories)

    if allowed:
        category_pool = [poi for poi in domain_pool if poi.category in allowed and poi.category not in avoided]
        if category_pool:
            return category_pool, False
        if domain_pool:
            return [poi for poi in domain_pool if poi.category not in avoided], True

    if domain_pool:
        return [poi for poi in domain_pool if poi.category not in avoided], False
    return all_pois[:BUCKET_LIMIT], True


def _extend_beam(
    beam: BeamCandidate,
    poi: ScoredPoi,
    *,
    budget_per_person: int,
    visit_duration_cap: int | None,
) -> BeamCandidate:
    prev = beam.pois[-1] if beam.pois else None
    travel = _travel_time_min(prev, poi)
    next_pois = (*beam.pois, poi)
    queue_wait = _queue_wait_min(poi)
    duration = beam.duration_min + travel + queue_wait + _visit_duration(poi, visit_duration_cap)
    cost = _avg_cost(next_pois)

    travel_penalty = travel / 60
    budget_penalty = max(0.0, cost - budget_per_person) / max(budget_per_person, 1)
    duplicate_category_penalty = 0.2 if prev and prev.category == poi.category else 0.0
    queue_penalty = queue_wait / 120
    score = beam.score + _poi_quality(poi) - travel_penalty - budget_penalty - duplicate_category_penalty - queue_penalty

    return BeamCandidate(
        pois=next_pois,
        duration_min=duration,
        estimated_cost_per_person=cost,
        score=score,
    )


def _generate_for_skeleton(
    skeleton: list[SlotHint],
    *,
    buckets: dict[str, list[ScoredPoi]],
    all_pois: list[ScoredPoi],
    budget_per_person: int,
    time_budget_minutes: int | None,
    queue_tolerance_minutes: int | None,
    visit_duration_cap: int | None,
    require_complete: bool = False,
) -> tuple[list[BeamCandidate], GenerationStats]:
    beams = [BeamCandidate(pois=(), duration_min=0, estimated_cost_per_person=0, score=0.0)]
    stats = GenerationStats()
    max_duration = int(time_budget_minutes * 1.2) if time_budget_minutes else None
    max_budget = int(budget_per_person * 1.2) if budget_per_person > 0 else None

    for slot in skeleton:
        pool, fallback = _candidate_pool(slot, buckets, all_pois)
        stats.used_fallback = stats.used_fallback or fallback
        next_beams: list[BeamCandidate] = []

        for beam in beams:
            used_ids = {poi.poi_id for poi in beam.pois}
            used_names = {_normalized_poi_name(poi.name) for poi in beam.pois}
            for poi in pool:
                if poi.poi_id in used_ids or _normalized_poi_name(poi.name) in used_names:
                    continue
                if queue_tolerance_minutes is not None and _queue_wait_min(poi) > queue_tolerance_minutes:
                    stats.pruned_by_queue += 1
                    continue
                expanded = _extend_beam(
                    beam,
                    poi,
                    budget_per_person=budget_per_person,
                    visit_duration_cap=visit_duration_cap,
                )
                if max_duration and expanded.duration_min > max_duration:
                    stats.pruned_by_time += 1
                    continue
                if max_budget and expanded.estimated_cost_per_person > max_budget:
                    stats.pruned_by_budget += 1
                    continue
                next_beams.append(expanded)

        if not next_beams:
            break
        beams = sorted(next_beams, key=lambda item: item.score, reverse=True)[:BEAM_WIDTH]

    if require_complete:
        return [beam for beam in beams if len(beam.pois) == len(skeleton)], stats
    return [beam for beam in beams if beam.pois], stats


def _format_time(minute: int) -> str:
    minute = max(0, minute)
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _parse_hhmm(value: object) -> int | None:
    if not isinstance(value, str) or ":" not in value:
        return None
    hour_text, minute_text = value.split(":", 1)
    if not (hour_text.isdigit() and minute_text.isdigit()):
        return None
    hour = int(hour_text)
    minute = int(minute_text)
    if hour < 0 or hour > 47 or minute < 0 or minute > 59:
        return None
    return hour * 60 + minute


def _round_up_to_quarter(minute: int) -> int:
    return ((minute + 14) // 15) * 15


def _round_down_to_quarter(minute: int) -> int:
    return (minute // 15) * 15


def _generic_visit_duration(slot: SlotHint) -> int:
    if any(category in SHORT_STAY_CATEGORIES for category in slot.categories):
        return 45
    if slot.domain == "dining":
        return 75
    return 60


def _estimate_route_duration_min(skeleton: list[SlotHint]) -> int:
    if not skeleton:
        return 0
    return sum(_generic_visit_duration(slot) for slot in skeleton) + max(0, len(skeleton) - 1) * 8


def _minute_from_input_ts(value: object) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone()
    return parsed.hour * 60 + parsed.minute


def _derive_start_minute(state: GraphState, constraints: dict, skeletons: list[list[SlotHint]]) -> int:
    query = str(constraints.get("raw_query") or state.get("user_query") or "")
    start_at = _parse_hhmm(constraints.get("start_at"))
    if start_at is not None:
        return _round_up_to_quarter(start_at)
    return_by = _parse_hhmm(constraints.get("return_by"))
    if return_by is not None:
        estimate = max((_estimate_route_duration_min(skeleton) for skeleton in skeletons), default=0)
        return _round_down_to_quarter(max(8 * 60, return_by - estimate - 30))

    if state.get("user_lat") is not None and state.get("user_lng") is not None and any(
        word in query for word in ("附近", "现在", "马上", "当前", "就近")
    ):
        current_minute = _minute_from_input_ts(state.get("input_ts"))
        # Late-night nearby requests should fall back to a useful scene time
        # rather than filtering every POI against closed business hours.
        if current_minute is not None and 8 * 60 <= current_minute <= 20 * 60:
            return _round_up_to_quarter(current_minute + 30)

    if any(word in query for word in ("下午", "午后")):
        return 14 * 60
    if any(word in query for word in ("午餐", "中午")):
        return 11 * 60 + 30
    if any(word in query for word in ("晚餐", "晚上", "夜宵")):
        return 18 * 60
    if any(word in query for word in ("咖啡", "下午茶")):
        return 14 * 60
    if constraints.get("domains") == ["sightseeing"]:
        return 9 * 60 + 30
    return DEFAULT_START_MINUTE


def _uses_late_nearby_default(state: GraphState, constraints: dict) -> bool:
    if _parse_hhmm(constraints.get("start_at")) is not None or _parse_hhmm(constraints.get("return_by")) is not None:
        return False
    query = str(constraints.get("raw_query") or state.get("user_query") or "")
    if state.get("user_lat") is None or state.get("user_lng") is None:
        return False
    if not any(word in query for word in ("附近", "现在", "马上", "当前", "就近")):
        return False
    current_minute = _minute_from_input_ts(state.get("input_ts"))
    return current_minute is not None and not 8 * 60 <= current_minute <= 20 * 60


async def _build_route(
    name: str,
    summary: str,
    pois: tuple[ScoredPoi, ...],
    *,
    start_minute: int,
    visit_duration_cap: int | None = None,
    weekday: int | None = None,
    budget_per_person: int = 0,
    mobility_preferences: list[str] | None = None,
    blueprint_id: str | None = None,
    style: str | None = None,
    precomputed_legs: tuple[RouteLeg, ...] | None = None,
    wait_for_first_opening: bool = False,
) -> RoutePlan:
    stops: list[RouteStop] = []
    legs: list[RouteLeg] = []
    cursor_min = start_minute
    prev: ScoredPoi | None = None

    for idx, poi in enumerate(pois, start=1):
        leg = (
            precomputed_legs[idx - 2]
            if prev and precomputed_legs is not None and idx - 2 < len(precomputed_legs)
            else (
                await TravelMatrixTool().select_leg(
                    prev,
                    poi,
                    budget_per_person=budget_per_person,
                    mobility_preferences=mobility_preferences,
                ) if prev else None
            )
        )
        if leg:
            legs.append(leg)
        travel = leg.duration_min if leg else 0
        physical_arrival = cursor_min + travel
        queue_wait = _queue_wait_min(poi)
        visit_duration = _visit_duration(poi, visit_duration_cap)
        opening_start = (
            next_opening_start(
                poi.opening_hours,
                physical_arrival,
                queue_wait + visit_duration,
                weekday=weekday,
            )
            if idx > 1 or wait_for_first_opening
            else physical_arrival
        )
        arrival = opening_start if opening_start is not None else physical_arrival
        slot_window = poi.slot_time_window or {}
        slot_start = _parse_hhmm(slot_window.get("start"))
        if slot_start is not None:
            arrival = max(arrival, slot_start)
        departure = arrival + queue_wait + visit_duration
        stops.append(
            RouteStop(
                sequence=idx,
                poi_id=poi.poi_id,
                poi_name=poi.name,
                category=poi.category,
                arrival_time=_format_time(arrival),
                departure_time=_format_time(departure),
                visit_duration_min=visit_duration,
                travel_time_from_prev_min=travel,
                travel_source=leg.source if leg else "origin",
                travel_estimated=leg.estimated if leg else True,
                travel_time_lower_bound_min=(max(1, int(leg.duration_min * 0.75)) if leg else 0),
                travel_time_upper_bound_min=(max(leg.duration_min, int(leg.duration_min * 1.4)) if leg else 0),
                travel_confidence=leg.confidence if leg else "high",
                queue_wait_min=queue_wait,
                opening_hours_text=poi.opening_hours_text,
                lat=poi.lat,
                lng=poi.lng,
                slot_id=poi.slot_id,
                slot_role=poi.slot_role,
                slot_source=poi.slot_source,
                slot_time_window=poi.slot_time_window,
            )
        )
        cursor_min = departure
        prev = poi

    return RoutePlan(
        plan_name=name,
        summary=summary,
        stops=stops,
        total_duration_min=cursor_min - start_minute,
        estimated_cost_per_person=_avg_cost(pois) + sum(leg.cost_per_person for leg in legs),
        legs=legs,
        blueprint_id=blueprint_id,
        style=style,
    )


def _route_area_name(state: GraphState, constraints: dict) -> str:
    geo_scope = state.get("geo_scope") or {}
    return geo_scope.get("resolved_name") or geo_scope.get("business_area") or constraints.get("district") or "上海"


def _route_is_open(route: RoutePlan, pois: tuple[ScoredPoi, ...], weekday: int | None) -> bool:
    by_id = {poi.poi_id: poi for poi in pois}
    for stop in route.stops:
        poi = by_id.get(stop.poi_id)
        if poi is None:
            continue
        arrival = _parse_hhmm(stop.arrival_time)
        departure = _parse_hhmm(stop.departure_time)
        if arrival is not None and departure is not None and is_open_during(poi.opening_hours, arrival, departure, weekday=weekday) is False:
            return False
    return True


def _route_respects_blueprint_window(
    route: RoutePlan,
    blueprint: ItineraryBlueprint,
    constraints: dict,
) -> bool:
    """Reject schedules that the shared validator would reject later."""
    route_end = _parse_hhmm(route.stops[-1].departure_time) if route.stops else None
    blueprint_end = _parse_hhmm(blueprint.return_by)
    if (
        constraints.get("return_by")
        and route_end is not None
        and blueprint_end is not None
        and route_end > blueprint_end
    ):
        return False
    for stop in route.stops:
        arrival = _parse_hhmm(stop.arrival_time)
        departure = _parse_hhmm(stop.departure_time)
        slot_window = stop.slot_time_window or {}
        window_start = _parse_hhmm(slot_window.get("start"))
        window_end = _parse_hhmm(slot_window.get("end"))
        if arrival is None or departure is None:
            return False
        if window_start is not None and arrival < window_start:
            return False
        if window_end is not None and departure > window_end:
            return False
    return True


def _candidate_start_minutes(
    state: GraphState,
    constraints: dict,
    pois: tuple[ScoredPoi, ...],
    base_start: int,
) -> list[int]:
    """Try POI opening times only when the user did not fix the schedule."""
    query = str(constraints.get("raw_query") or state.get("user_query") or "")
    explicit_clock = re.search(
        r"(?:上午|早上|中午|下午|午后|晚上|夜间)?\s*(?:从|在)?\s*"
        r"(?:\d{1,2}|[一二两三四五六七八九十]+)\s*"
        r"(?:点(?:\s*(?:半|\d{1,2}\s*分?))?|:\d{2})",
        query,
    )
    period_mention = re.search(r"上午|早上|中午|下午|午后|晚上|夜间", query)
    start_at_is_hard = bool(constraints.get("start_at")) and not (period_mention and not explicit_clock)
    if explicit_clock or start_at_is_hard or constraints.get("return_by") or any(
        word in query for word in ("现在", "马上", "立刻")
    ):
        return [base_start]

    starts = [base_start]
    for poi in pois:
        for interval in poi.opening_hours:
            opening = _parse_hhmm(interval.get("open"))
            if opening is not None and 8 * 60 <= opening <= 20 * 60:
                starts.append(max(base_start, opening))
    return list(dict.fromkeys(starts))


def _slot_to_dict(slot: SlotHint) -> dict:
    return {
        "domain": slot.domain,
        "categories": list(slot.categories),
        "avoid_categories": list(slot.avoid_categories),
        "note": slot.note,
    }


async def _generate_from_activity_blueprints(
    state: GraphState,
    constraints: dict,
    all_pois: list[ScoredPoi],
) -> tuple[list[RoutePlan], dict, GenerationStats]:
    """Search exact slots while carrying absolute time and real travel legs."""

    by_slot = {
        slot_id: [ScoredPoi.model_validate(item) for item in items[:4]]
        for slot_id, items in (state.get("candidate_pois_by_slot") or {}).items()
    }
    blueprints = [
        ItineraryBlueprint.model_validate(item)
        for item in state.get("activity_blueprints") or []
    ]
    stats = GenerationStats()
    routes: list[RoutePlan] = []
    missing_required: list[str] = []
    weekday = weekday_from_date(state.get("input_ts"))
    time_budget = constraints.get("time_budget_minutes")
    schedule_envelope = constraints.get("schedule_envelope") or {}
    max_duration = int(
        schedule_envelope.get("max_duration_minutes")
        or time_budget
        or 12 * 60
    )
    target_duration = int(
        schedule_envelope.get("target_duration_minutes")
        or time_budget
        or max_duration
    )
    budget = int(constraints.get("budget_per_person") or 0)
    compiled_atoms = (state.get("compiled_constraints") or {}).get("atoms") or []
    budget_hard = any(
        item.get("field") == "budget_per_person" and item.get("strength") == "hard"
        for item in compiled_atoms
    )
    leg_cache: dict[tuple[str, str], RouteLeg] = {}
    failures: list[dict] = []

    for blueprint in blueprints:
        visit_slot_count = sum(slot.role != "rest" for slot in blueprint.slots)
        visit_duration_cap = _dense_visit_cap(visit_slot_count, time_budget)
        start_minute = _parse_hhmm(blueprint.start_at) or DEFAULT_START_MINUTE
        beams = [ScheduledBeam(
            pois=(),
            legs=(),
            start_minute=start_minute,
            cursor_minute=start_minute,
            estimated_cost_per_person=0,
            score=0.0,
        )]
        failed = False
        for slot in blueprint.slots:
            if slot.role == "rest":
                continue
            pool = by_slot.get(slot.slot_id) or []
            if not pool:
                if slot.required:
                    missing_required.append(slot.slot_id)
                    failed = True
                    break
                continue
            next_beams: list[ScheduledBeam] = list(beams) if not slot.required else []
            for beam in beams:
                used_ids = {poi.poi_id for poi in beam.pois}
                used_names = {_normalized_poi_name(poi.name) for poi in beam.pois}
                for poi in pool:
                    if poi.poi_id in used_ids or _normalized_poi_name(poi.name) in used_names:
                        continue
                    queue_tolerance = constraints.get("queue_tolerance_minutes")
                    if queue_tolerance is not None and _queue_wait_min(poi) > int(queue_tolerance):
                        stats.pruned_by_queue += 1
                        continue
                    prev = beam.pois[-1] if beam.pois else None
                    leg = None
                    if prev is not None:
                        key = (prev.poi_id, poi.poi_id)
                        leg = leg_cache.get(key)
                        if leg is None:
                            leg = await TravelMatrixTool().select_leg(
                                prev,
                                poi,
                                budget_per_person=budget,
                                mobility_preferences=constraints.get("mobility_preferences") or [],
                            )
                            leg_cache[key] = leg
                    travel = leg.duration_min if leg else 0
                    physical_arrival = beam.cursor_minute + travel
                    queue_wait = _queue_wait_min(poi)
                    visit_duration = _visit_duration(poi, visit_duration_cap)
                    opening_start = next_opening_start(
                        poi.opening_hours,
                        physical_arrival,
                        queue_wait + visit_duration,
                        weekday=weekday,
                    )
                    if opening_start is None:
                        continue
                    arrival = opening_start
                    slot_window = poi.slot_time_window or {}
                    window_start = _parse_hhmm(slot_window.get("start"))
                    window_end = _parse_hhmm(slot_window.get("end"))
                    if window_start is not None:
                        arrival = max(arrival, window_start)
                    departure = arrival + queue_wait + visit_duration
                    if window_end is not None and departure > window_end:
                        stats.pruned_by_time += 1
                        continue
                    elapsed = departure - beam.start_minute
                    if elapsed > max_duration:
                        stats.pruned_by_time += 1
                        continue
                    next_pois = (*beam.pois, poi)
                    next_legs = (*beam.legs, leg) if leg else beam.legs
                    next_cost = _avg_cost(next_pois) + sum(item.cost_per_person for item in next_legs)
                    if budget_hard and budget > 0 and next_cost > budget:
                        stats.pruned_by_budget += 1
                        continue
                    travel_penalty = travel / 60
                    budget_penalty = max(0.0, next_cost - budget) / max(budget, 1) if budget else 0.0
                    score = beam.score + _poi_quality(poi) - travel_penalty - budget_penalty
                    if slot.requirement_level == "policy":
                        score += 0.4
                    next_beams.append(ScheduledBeam(
                        pois=next_pois,
                        legs=next_legs,
                        start_minute=beam.start_minute,
                        cursor_minute=departure,
                        estimated_cost_per_person=next_cost,
                        score=score,
                    ))
            if not next_beams:
                if slot.required:
                    missing_required.append(slot.slot_id)
                    failures.append({
                        "failure_type": "temporal_conflict",
                        "slot_id": slot.slot_id,
                        "candidate_count": len(pool),
                        "blocking_constraints": ["time_or_opening_or_budget"],
                    })
                    failed = True
                break
            ranked = sorted(
                next_beams,
                key=lambda item: (
                    -item.score,
                    abs((item.cursor_minute - item.start_minute) - target_duration),
                    tuple(poi.poi_id for poi in item.pois),
                ),
            )
            beams = ranked[:BLUEPRINT_BEAM_WIDTH]
        if failed:
            continue

        for beam in sorted(
            beams,
            key=lambda item: (
                -item.score,
                abs((item.cursor_minute - item.start_minute) - target_duration),
                tuple(poi.poi_id for poi in item.pois),
            ),
        ):
            if not beam.pois:
                continue
            route = await _build_route(
                name=f"{_route_area_name(state, constraints)}·{'均衡' if blueprint.style == 'balanced' else '体验'}路线",
                summary=f"{len(beam.pois)} 站 · {_format_time(beam.start_minute)} 出发 · 人均约 {beam.estimated_cost_per_person} 元",
                pois=beam.pois,
                start_minute=beam.start_minute,
                visit_duration_cap=visit_duration_cap,
                weekday=weekday,
                budget_per_person=budget,
                mobility_preferences=constraints.get("mobility_preferences") or [],
                blueprint_id=blueprint.blueprint_id,
                style=blueprint.style,
                precomputed_legs=beam.legs,
                wait_for_first_opening=True,
            )
            if route.total_duration_min > max_duration:
                stats.pruned_by_time += 1
                continue
            if budget_hard and budget > 0 and route.estimated_cost_per_person > budget:
                stats.pruned_by_budget += 1
                continue
            if not _route_respects_blueprint_window(route, blueprint, constraints):
                stats.pruned_by_time += 1
                continue
            if not _route_is_open(route, beam.pois, weekday):
                continue
            routes.append(route)
            break
        if len(routes) >= 2:
            break

    return routes, {
        "mode": "activity_blueprint",
        "blueprint_count": len(blueprints),
        "candidate_count": len(all_pois),
        "candidate_counts_by_slot": {
            slot_id: len(items) for slot_id, items in by_slot.items()
        },
        "generation_top_k_per_slot": 4,
        "missing_required_slots": list(dict.fromkeys(missing_required)),
        "target_stop_count": max((len(item.stops) for item in routes), default=0),
        "minimum_stop_count": int(constraints.get("anchor_count_explicit") or 0),
        "target_stop_count_enforced": bool(constraints.get("anchor_count_explicit")),
        "pruned_by_time": stats.pruned_by_time,
        "pruned_by_budget": stats.pruned_by_budget,
        "pruned_by_queue": stats.pruned_by_queue,
        "used_fallback": stats.used_fallback,
        "planning_failures": failures,
        "travel_matrix_edge_count": len(leg_cache),
        "budget_hard": budget_hard,
        "visit_duration_cap_min": min(
            (
                _dense_visit_cap(
                    sum(slot.role != "rest" for slot in blueprint.slots),
                    time_budget,
                )
                for blueprint in blueprints
            ),
            default=None,
            key=lambda value: value if value is not None else 10**9,
        ),
    }, stats


async def route_generate(state: GraphState) -> dict:
    constraints = state["constraints"]
    assert constraints is not None

    all_pois = [ScoredPoi.model_validate(p) for p in state["candidate_pois"]]
    if not all_pois:
        return phase_update(
            "route_generate",
            summary="generated 0 routes",
            candidate_routes=[],
            route_generation_meta={"candidate_count": 0, "skeletons": []},
        )

    if (
        settings.joint_route_solver_enabled
        and state.get("activity_blueprints")
        and state.get("candidate_pois_by_slot")
    ):
        routes, route_generation_meta, generation_stats = await _generate_from_activity_blueprints(
            state, constraints, all_pois
        )
        travel_sources = {
            leg.source for route in routes for leg in route.legs
        }
        fallback_used = any(leg.fallback_used for route in routes for leg in route.legs)
        estimated_count = sum(leg.estimated for route in routes for leg in route.legs)
        leg_count = sum(len(route.legs) for route in routes)
        update = phase_update(
            "route_generate",
            summary=f"generated {len(routes)} blueprint routes",
            candidate_routes=[route.model_dump(mode="json") for route in routes],
            route_generation_meta={
                **route_generation_meta,
                "travel_leg_count": leg_count,
                "estimated_travel_leg_count": estimated_count,
                "real_travel_leg_count": leg_count - estimated_count,
            },
            tool_calls=[{
                "operation": "travel_time",
                "status": "fallback" if fallback_used else "success",
                "source": ",".join(sorted(travel_sources)) or "none",
                "tool": "TravelMatrixTool",
                "estimated": bool(estimated_count),
                "fallback_used": fallback_used,
                "call_count": route_generation_meta.get("travel_matrix_edge_count", leg_count),
            }],
            degraded=bool(state.get("degraded")) or bool(route_generation_meta["missing_required_slots"]),
            planning_failures=route_generation_meta.get("planning_failures") or [],
        )
        update["phase_log"][0].update({
            "route_count": len(routes),
            "travel_leg_count": leg_count,
            "estimated_travel_leg_count": estimated_count,
            "missing_required_slots": route_generation_meta["missing_required_slots"],
        })
        if generation_stats.used_fallback:
            update["relaxed_constraints"] = ["route_generate_bucket_relaxed"]
        return update

    ranked_pois = sorted(all_pois, key=_poi_quality, reverse=True)
    pinned_pois = [poi for poi in ranked_pois if "match:name_exact" in poi.tags]
    regular_pois = [poi for poi in ranked_pois if "match:name_exact" not in poi.tags]
    all_pois = _dedupe_pois_by_name(pinned_pois + regular_pois)
    all_pois = all_pois[: max(BUCKET_LIMIT * 3, BUCKET_LIMIT, len(pinned_pois))]
    buckets = _group_pois(all_pois)
    domains = _ordered_domains(constraints.get("domains"))
    poi_count = max(1, int(constraints.get("poi_count") or 3))
    query = str(constraints.get("raw_query") or state.get("user_query") or "")
    enforce_target = should_enforce_poi_count(query)
    minimum_stop_count = derive_minimum_poi_count(
        query,
        constraints.get("time_budget_minutes"),
        target_count=poi_count,
        domains=domains,
    )
    skeletons = _route_skeletons(
        domains,
        poi_count,
        query,
        minimum_stop_count=minimum_stop_count,
    )
    visit_duration_cap = _dense_visit_cap(poi_count, constraints.get("time_budget_minutes"))
    start_minute = _derive_start_minute(state, constraints, skeletons)
    late_nearby_default = _uses_late_nearby_default(state, constraints)

    candidates: list[BeamCandidate] = []
    generation_stats = GenerationStats()
    for skeleton in skeletons:
        generated, stats = _generate_for_skeleton(
            skeleton,
            buckets=buckets,
            all_pois=all_pois,
            budget_per_person=int(constraints["budget_per_person"]),
            time_budget_minutes=constraints.get("time_budget_minutes"),
            queue_tolerance_minutes=constraints.get("queue_tolerance_minutes"),
            visit_duration_cap=visit_duration_cap,
            require_complete=enforce_target,
        )
        if any(slot.categories for slot in skeleton):
            generated = [
                BeamCandidate(
                    pois=beam.pois,
                    duration_min=beam.duration_min,
                    estimated_cost_per_person=beam.estimated_cost_per_person,
                    score=beam.score + len(beam.pois),
                )
                for beam in generated
            ]
        candidates.extend(generated)
        generation_stats.used_fallback = generation_stats.used_fallback or stats.used_fallback
        generation_stats.pruned_by_time += stats.pruned_by_time
        generation_stats.pruned_by_budget += stats.pruned_by_budget

    if not candidates:
        queue_tolerance = constraints.get("queue_tolerance_minutes")
        fallback_pool = [poi for poi in all_pois if queue_tolerance is None or _queue_wait_min(poi) <= int(queue_tolerance)]
        fallback_pois = tuple((fallback_pool or all_pois)[: min(poi_count, len(fallback_pool or all_pois))])
        candidates = [
            BeamCandidate(
                pois=fallback_pois,
                duration_min=sum(_visit_duration(poi, visit_duration_cap) + _queue_wait_min(poi) for poi in fallback_pois),
                estimated_cost_per_person=_avg_cost(fallback_pois),
                score=sum(_poi_quality(poi) for poi in fallback_pois),
            )
        ]
        generation_stats.used_fallback = True

    unique: dict[tuple[str, ...], BeamCandidate] = {}
    for candidate in sorted(candidates, key=lambda item: item.score, reverse=True):
        key = tuple(poi.poi_id for poi in candidate.pois)
        unique.setdefault(key, candidate)

    area = _route_area_name(state, constraints)
    routes: list[RoutePlan] = []
    pruned_by_hours = 0
    route_start_minutes: list[int] = []
    weekday = weekday_from_date(state.get("input_ts"))
    for candidate in unique.values():
        for candidate_start in _candidate_start_minutes(state, constraints, candidate.pois, start_minute):
            route = await _build_route(
                name=f"{area}路线{len(routes) + 1}",
                summary=f"{len(candidate.pois)} 站 · {_format_time(candidate_start)} 出发 · 人均约 {candidate.estimated_cost_per_person} 元",
                pois=candidate.pois,
                start_minute=candidate_start,
                visit_duration_cap=visit_duration_cap,
                weekday=weekday,
            )
            time_budget = constraints.get("time_budget_minutes")
            if time_budget is not None and route.total_duration_min > int(time_budget):
                generation_stats.pruned_by_time += 1
                continue
            if not _route_is_open(route, candidate.pois, weekday):
                pruned_by_hours += 1
                continue
            routes.append(route)
            route_start_minutes.append(candidate_start)
            break
        if len(routes) >= MAX_ROUTES:
            break

    effective_start = route_start_minutes[0] if route_start_minutes else start_minute
    start_adjusted_for_hours = any(item != start_minute for item in route_start_minutes)

    route_generation_meta = {
        "candidate_count": len(all_pois),
        "target_stop_count": min(poi_count, MAX_ROUTE_STOPS),
        "target_stop_count_enforced": enforce_target,
        "minimum_stop_count": min(minimum_stop_count, MAX_ROUTE_STOPS),
        "bucket_counts": {domain: len(items) for domain, items in buckets.items()},
        "skeletons": [[_slot_to_dict(slot) for slot in skeleton] for skeleton in skeletons],
        "start_time": _format_time(effective_start),
        "start_time_adjusted_for_hours": start_adjusted_for_hours,
        "pruned_by_time": generation_stats.pruned_by_time,
        "pruned_by_budget": generation_stats.pruned_by_budget,
        "pruned_by_queue": generation_stats.pruned_by_queue,
        "pruned_by_hours": pruned_by_hours,
        "used_fallback": generation_stats.used_fallback,
        "visit_duration_cap_min": visit_duration_cap,
    }

    travel_sources = {stop.travel_source for route in routes for stop in route.stops if stop.travel_source != "origin"}
    fallback_used = any(stop.travel_estimated and stop.travel_source == "mock_haversine" for route in routes for stop in route.stops)
    update = phase_update(
        "route_generate",
        summary=f"generated {len(routes)} routes",
        candidate_routes=[route.model_dump(mode="json") for route in routes],
        route_generation_meta=route_generation_meta,
        tool_calls=[
            {
                "operation": "travel_time",
                "status": "success",
                "source": ",".join(sorted(travel_sources)) or "origin",
                "estimated": fallback_used,
                "fallback_used": fallback_used,
                "call_count": sum(max(0, len(route.stops) - 1) for route in routes),
            }
        ],
    )
    update["phase_log"][0].update({
        "route_count": len(routes),
        "fallback_used": generation_stats.used_fallback,
    })
    if generation_stats.used_fallback:
        update["relaxed_constraints"] = ["route_generate_bucket_relaxed"]
    if late_nearby_default:
        update["assumptions"] = [{
            "slot": "start_at",
            "assumed_value": _format_time(start_minute),
            "source": "scene_default",
            "message": f"当前时间较晚，已按可营业时段默认安排 {_format_time(start_minute)} 出发",
            "overridable": True,
        }]
    elif start_adjusted_for_hours:
        update["assumptions"] = [
            *(state.get("assumptions") or []),
            {
                "slot": "start_at",
                "assumed_value": _format_time(effective_start),
                "source": "opening_hours",
                "message": f"未指定出发时间，已按营业时间安排 {_format_time(effective_start)} 开始",
                "overridable": True,
            },
        ]
    return update
