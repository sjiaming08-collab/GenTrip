"""[3] route_generate — controlled route generation from candidate POIs."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from ...models.route import RoutePlan, RouteStop, ScoredPoi
from ...services.travel_time import mock_travel_estimator, travel_time_service
from ...services.poi_hours import is_open_during, weekday_from_date
from ..state import GraphState, phase_update

BUCKET_LIMIT = 6
BEAM_WIDTH = 4
MAX_SKELETONS = 3
MAX_ROUTES = 5
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


@dataclass
class GenerationStats:
    used_fallback: bool = False
    pruned_by_time: int = 0
    pruned_by_budget: int = 0
    pruned_by_queue: int = 0


def _domain_of_poi(poi: ScoredPoi) -> str:
    if poi.dimension:
        return poi.dimension
    if poi.category in DINING_CATEGORIES:
        return "dining"
    if poi.category in SHOPPING_CATEGORIES:
        return "shopping"
    return "sightseeing"


def _visit_duration(poi: ScoredPoi) -> int:
    domain = _domain_of_poi(poi)
    if poi.category in SHORT_STAY_CATEGORIES:
        return 45
    if domain == "dining":
        return 75
    return 60


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
        buckets[key] = pinned + regular[: max(0, BUCKET_LIMIT - len(pinned))]
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


def _trim_skeleton(items: list[SlotHint], poi_count: int) -> list[SlotHint]:
    target = max(1, min(poi_count, 3))
    return items[:target]


def _route_skeletons(domains: list[str], poi_count: int, query: str = "") -> list[list[SlotHint]]:
    domain_set = set(domains)
    skeletons: list[list[SlotHint]] = []
    mentioned_categories = _mentioned_categories(query)

    if mentioned_categories and "dining" in domain_set:
        explicit_slots = [_slot("dining", (category,), category) for category in mentioned_categories]
        skeletons.append(explicit_slots)

    if {"dining", "sightseeing"}.issubset(domain_set):
        skeletons.extend(
            [
                [_slot("sightseeing"), _slot("dining"), _slot("sightseeing")],
                [_slot("dining"), _slot("sightseeing"), _slot("dining")],
                [_slot("sightseeing"), _slot("dining")],
            ]
        )
    elif {"shopping", "dining"}.issubset(domain_set):
        skeletons.extend(
            [
                [_slot("shopping"), _slot("dining"), _slot("shopping")],
                [_slot("dining"), _slot("shopping")],
                [_slot("shopping"), _slot("dining")],
            ]
        )
    elif domains == ["dining"]:
        target = max(1, min(poi_count, 2))
        skeletons.extend([[_slot("dining") for _ in range(target)], [_slot("dining")]])
    elif domains == ["sightseeing"]:
        skeletons.extend(
            [
                [_slot("sightseeing") for _ in range(max(1, min(poi_count, 3)))],
                [_slot("sightseeing") for _ in range(max(1, min(poi_count, 2)))],
            ]
        )
    elif domains == ["shopping"]:
        skeletons.extend([[_slot("shopping") for _ in range(max(1, min(poi_count, 2)))], [_slot("shopping")]])
    else:
        mixed: list[SlotHint] = []
        target = max(1, min(poi_count, 3))
        while len(mixed) < target:
            mixed.extend(_slot(domain) for domain in domains)
        skeletons.extend([mixed[:target], [_slot(domain) for domain in domains[: min(len(domains), target)]]])

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
) -> BeamCandidate:
    prev = beam.pois[-1] if beam.pois else None
    travel = _travel_time_min(prev, poi)
    next_pois = (*beam.pois, poi)
    queue_wait = _queue_wait_min(poi)
    duration = beam.duration_min + travel + queue_wait + _visit_duration(poi)
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
                expanded = _extend_beam(beam, poi, budget_per_person=budget_per_person)
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
) -> RoutePlan:
    stops: list[RouteStop] = []
    cursor_min = start_minute
    prev: ScoredPoi | None = None

    for idx, poi in enumerate(pois, start=1):
        estimate = await travel_time_service.estimate(
            prev.lat,
            prev.lng,
            poi.lat,
            poi.lng,
            mode="walking",
        ) if prev else None
        travel = estimate.duration_min if estimate else 0
        arrival = cursor_min + travel
        queue_wait = _queue_wait_min(poi)
        visit_duration = _visit_duration(poi)
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
                travel_source=estimate.source if estimate else "origin",
                travel_estimated=estimate.estimated if estimate else True,
                travel_time_lower_bound_min=estimate.min_duration_min if estimate else 0,
                travel_time_upper_bound_min=estimate.max_duration_min if estimate else 0,
                travel_confidence=estimate.confidence if estimate else "high",
                queue_wait_min=queue_wait,
                lat=poi.lat,
                lng=poi.lng,
            )
        )
        cursor_min = departure
        prev = poi

    return RoutePlan(
        plan_name=name,
        summary=summary,
        stops=stops,
        total_duration_min=cursor_min - start_minute,
        estimated_cost_per_person=_avg_cost(pois),
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


def _candidate_start_minutes(
    state: GraphState,
    constraints: dict,
    pois: tuple[ScoredPoi, ...],
    base_start: int,
) -> list[int]:
    """Try POI opening times only when the user did not fix the schedule."""
    query = str(constraints.get("raw_query") or state.get("user_query") or "")
    if constraints.get("start_at") or constraints.get("return_by") or any(word in query for word in ("现在", "马上", "立刻")):
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

    ranked_pois = sorted(all_pois, key=_poi_quality, reverse=True)
    pinned_pois = [poi for poi in ranked_pois if "match:name_exact" in poi.tags]
    regular_pois = [poi for poi in ranked_pois if "match:name_exact" not in poi.tags]
    all_pois = _dedupe_pois_by_name(pinned_pois + regular_pois)
    all_pois = all_pois[: max(BUCKET_LIMIT * 3, BUCKET_LIMIT, len(pinned_pois))]
    buckets = _group_pois(all_pois)
    domains = _ordered_domains(constraints.get("domains"))
    poi_count = max(1, int(constraints.get("poi_count") or 3))
    query = str(constraints.get("raw_query") or state.get("user_query") or "")
    skeletons = _route_skeletons(domains, poi_count, query)
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
                duration_min=sum(_visit_duration(poi) + _queue_wait_min(poi) for poi in fallback_pois),
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
    for candidate in unique.values():
        for candidate_start in _candidate_start_minutes(state, constraints, candidate.pois, start_minute):
            route = await _build_route(
                name=f"{area}路线{len(routes) + 1}",
                summary=f"{len(candidate.pois)} 站 · {_format_time(candidate_start)} 出发 · 人均约 {candidate.estimated_cost_per_person} 元",
                pois=candidate.pois,
                start_minute=candidate_start,
            )
            time_budget = constraints.get("time_budget_minutes")
            if time_budget is not None and route.total_duration_min > int(time_budget):
                generation_stats.pruned_by_time += 1
                break
            if not _route_is_open(route, candidate.pois, weekday_from_date(state.get("input_ts"))):
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
        "bucket_counts": {domain: len(items) for domain, items in buckets.items()},
        "skeletons": [[_slot_to_dict(slot) for slot in skeleton] for skeleton in skeletons],
        "start_time": _format_time(effective_start),
        "start_time_adjusted_for_hours": start_adjusted_for_hours,
        "pruned_by_time": generation_stats.pruned_by_time,
        "pruned_by_budget": generation_stats.pruned_by_budget,
        "pruned_by_queue": generation_stats.pruned_by_queue,
        "pruned_by_hours": pruned_by_hours,
        "used_fallback": generation_stats.used_fallback,
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
