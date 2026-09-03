"""[2] poi_retrieve — broad legacy retrieval or independent slot retrieval."""

import asyncio
import math

from ...models.blueprint import ItineraryBlueprint
from ...models.constraints import Assumption, IntentDomain
from ...models.retrieval import DomainSpec, RetrievalPlan, RetrievalResult
from ...models.route import ScoredPoi
from ...config import settings
from ...services.poi_query_parser import parse_retrieval_plan
from ...services.category_taxonomy import DEFAULT_MEAL_CATEGORIES, resolve_domain_leaves
from ...services.planner_tools import PoiEnrichmentTool, PoiSearchTool
from ...services.poi_hours import is_open_during, parse_hhmm, weekday_from_date
from ..state import GraphState, phase_update, utc_now_iso


def _group_by_dimension(result: RetrievalResult) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for poi in result.pois:
        key = poi.dimension or "unknown"
        grouped.setdefault(key, []).append(poi.model_dump(mode="json"))
    return grouped


def _distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    h = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lng / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def _slot_score(
    poi: ScoredPoi,
    slot: dict,
    plan: RetrievalPlan,
    *,
    weekday: int | None = None,
) -> float:
    categories = [str(item) for item in slot.get("categories") or []]
    semantic = 1.0 if any(
        item in poi.category or poi.category in item for item in categories
    ) else (0.75 if poi.dimension == slot.get("domain") else 0.5)
    quality = max(0.0, min(1.0, poi.rating / 5.0))
    filters = plan.filters
    if filters.center_lat is not None and filters.center_lng is not None:
        distance = _distance_m(filters.center_lat, filters.center_lng, poi.lat, poi.lng)
        spatial = max(0.0, 1.0 - distance / max(float(filters.radius_m or 5000), 1000.0))
    else:
        spatial = 0.5
    expected_window = slot.get("expected_time_window") or slot.get("time_window") or {}
    expected_start = parse_hhmm(expected_window.get("start"))
    expected_end = parse_hhmm(expected_window.get("end"))
    if expected_start is not None and expected_end is not None:
        opening_fit = is_open_during(
            poi.opening_hours, expected_start, expected_end, weekday=weekday
        )
        hours = 1.0 if opening_fit is True else (0.55 if opening_fit is None else 0.0)
    else:
        hours = 1.0 if poi.opening_hours else 0.55
    budget = filters.budget_per_person or 0
    budget_fit = 1.0 if not budget or not poi.price_per_person or poi.price_per_person <= budget else max(
        0.0, budget / max(poi.price_per_person, 1)
    )
    return round(0.30 * semantic + 0.25 * quality + 0.20 * spatial + 0.15 * hours + 0.10 * budget_fit, 4)


def _decorate_slot_poi(
    poi: ScoredPoi,
    *,
    blueprint: ItineraryBlueprint,
    slot: dict,
    provider: str,
    plan: RetrievalPlan,
    weekday: int | None = None,
) -> ScoredPoi:
    keywords = list(dict.fromkeys([
        *[str(item) for item in slot.get("categories") or []],
        *[str(item) for item in slot.get("activity_tags") or []],
    ]))
    score = _slot_score(poi, slot, plan, weekday=weekday)
    return poi.model_copy(
        update={
            "composite_score": score,
            "slot_id": slot["slot_id"],
            "blueprint_id": blueprint.blueprint_id,
            "slot_role": slot.get("role"),
            "slot_source": slot.get("source"),
            "slot_required": bool(slot.get("required", True)),
            "slot_duration_minutes": slot.get("duration_minutes"),
            "slot_time_window": slot.get("time_window"),
            "slot_expected_time_window": slot.get("expected_time_window"),
            "recall_keywords": keywords,
            "provider": provider,
            "field_sources": {
                "identity": provider,
                "coordinates": provider,
                "rating": provider,
                "price": provider,
                "opening_hours": provider,
            },
            "match_reasons": list(dict.fromkeys([*poi.match_reasons, "slot_domain", *( ["slot_category"] if any(item in poi.category or poi.category in item for item in keywords) else [])])),
            "match_explanation": f"匹配槽位 {slot['slot_id']}，加权得分 {score:.2f}",
        }
    )


def _allocate_slot_query_limits(jobs: list[tuple[tuple, int, bool]]) -> dict[tuple, int]:
    """Allocate a deterministic per-run provider clause budget.

    Every required slot gets one clause before optional slots; remaining
    clauses are distributed round-robin up to the per-slot cap.
    """
    if not jobs:
        return {}
    total_budget = max(1, int(settings.poi_queries_per_run))
    per_slot = max(1, int(settings.poi_queries_per_slot))
    ordered = sorted(
        enumerate(jobs),
        key=lambda item: (not item[1][2], item[0]),
    )
    allocated: dict[tuple, int] = {}
    for _, (signature, _desired, _required) in ordered:
        if total_budget <= 0:
            break
        allocated[signature] = 1
        total_budget -= 1
    while total_budget > 0:
        progressed = False
        for _, (signature, desired, _required) in ordered:
            current = allocated.get(signature, 0)
            target = min(max(1, desired), per_slot)
            if current >= target:
                continue
            allocated[signature] = current + 1
            total_budget -= 1
            progressed = True
            if total_budget <= 0:
                break
        if not progressed:
            break
    return allocated


def _slot_retrieval_plan(slot_model, base_plan: RetrievalPlan, state: GraphState) -> tuple[tuple, RetrievalPlan, int]:
    domain = slot_model.domain or IntentDomain.SIGHTSEEING
    categories = sorted(resolve_domain_leaves(domain, slot_model.categories))
    if not categories:
        if slot_model.role == "meal":
            categories = list(DEFAULT_MEAL_CATEGORIES)
        else:
            categories = next(
                (list(spec.categories or []) for spec in base_plan.domains if spec.domain == domain),
                [],
            ) or None
    expected_window = slot_model.expected_time_window or slot_model.time_window
    search_keywords = (
        [] if slot_model.role == "meal" and set(categories or []) == set(DEFAULT_MEAL_CATEGORIES)
        else list(dict.fromkeys(slot_model.activity_tags))
    )
    signature = (
        domain.value,
        tuple(categories or []),
        tuple(search_keywords),
        slot_model.spatial_policy,
        expected_window.start if expected_window else None,
        expected_window.end if expected_window else None,
    )
    desired = max(1, len(slot_model.categories) + len(search_keywords))
    plan = RetrievalPlan(
        raw_query=" ".join([
            state["user_query"],
            *slot_model.categories,
            *slot_model.activity_tags,
        ]),
        filters=base_plan.filters,
        domains=[DomainSpec(
            domain=domain,
            categories=categories,
            search_keywords=search_keywords,
        )],
    )
    return signature, plan, desired


async def _retrieve_by_blueprint_slots(state: GraphState) -> dict:
    base_plan = parse_retrieval_plan(state)
    blueprints = [
        ItineraryBlueprint.model_validate(item)
        for item in state.get("activity_blueprints") or []
    ]
    slot_records: dict[str, list[tuple[dict, object, tuple | None]]] = {}
    jobs: dict[tuple, tuple[RetrievalPlan, int, bool]] = {}
    for blueprint in blueprints:
        records: list[tuple[dict, object, tuple | None]] = []
        for slot_model in blueprint.slots:
            slot = slot_model.model_dump(mode="json")
            if slot_model.role == "rest":
                records.append((slot, slot_model, None))
                continue
            signature, plan, desired = _slot_retrieval_plan(slot_model, base_plan, state)
            records.append((slot, slot_model, signature))
            if signature not in jobs:
                jobs[signature] = (plan, desired, bool(slot_model.required))
            elif slot_model.required and not jobs[signature][2]:
                jobs[signature] = (jobs[signature][0], jobs[signature][1], True)
        slot_records[blueprint.blueprint_id] = records

    allocations = _allocate_slot_query_limits([
        (signature, desired, required)
        for signature, (_plan, desired, required) in jobs.items()
    ])
    semaphore = asyncio.Semaphore(max(1, int(settings.poi_slot_concurrency)))
    search_tool = PoiSearchTool()

    async def run_job(signature: tuple, plan: RetrievalPlan):
        query_limit = allocations.get(signature, 0)
        if query_limit <= 0:
            return RetrievalResult(pois=[], plan=plan), "none", True, False, plan
        bounded_plan = plan.model_copy(update={"provider_query_limit": query_limit})
        async with semaphore:
            outcome = await search_tool.run(bounded_plan, limit=25)
        return outcome.result, outcome.source, outcome.degraded, outcome.cache_hit, bounded_plan

    if settings.poi_slot_parallel_enabled:
        tasks = {
            signature: asyncio.create_task(run_job(signature, plan))
            for signature, (plan, _desired, _required) in jobs.items()
        }
    else:
        tasks = {}
        for signature, (plan, _desired, _required) in jobs.items():
            task = asyncio.create_task(run_job(signature, plan))
            await task
            tasks[signature] = task

    raw_outcomes = await asyncio.gather(*tasks.values(), return_exceptions=True)
    job_results: dict[tuple, tuple[RetrievalResult, str, bool, bool, RetrievalPlan]] = {}
    for (signature, (plan, _desired, _required)), raw in zip(jobs.items(), raw_outcomes):
        if isinstance(raw, BaseException):
            job_results[signature] = (
                RetrievalResult(pois=[], plan=plan), "none", True, False, plan
            )
        else:
            job_results[signature] = raw

    by_slot: dict[str, list[dict]] = {}
    all_candidates: dict[str, ScoredPoi] = {}
    assumptions: list[dict] = []
    relaxed: list[str] = []
    provider_sources: set[str] = set()
    provider_calls = sum(1 for value in allocations.values() if value > 0)
    missing_required: list[str] = []
    updated_blueprints: list[dict] = []
    weekday = weekday_from_date(state.get("input_ts"))

    for blueprint in blueprints:
        kept_slots: list[dict] = []
        for slot, slot_model, signature in slot_records[blueprint.blueprint_id]:
            if signature is None:
                kept_slots.append(slot)
                continue
            result, source, degraded, _cache_hit, plan = job_results[signature]
            result.pois = PoiEnrichmentTool().run(result.pois, provider=source)
            provider_sources.add(source)
            candidates = [
                _decorate_slot_poi(
                    poi,
                    blueprint=blueprint,
                    slot=slot,
                    provider=source,
                    plan=plan,
                    weekday=weekday,
                )
                for poi in result.pois
            ]
            candidates = sorted(candidates, key=lambda item: item.composite_score, reverse=True)[:8]
            if not candidates:
                if slot_model.required:
                    missing_required.append(slot_model.slot_id)
                    kept_slots.append(slot)
                # Optional empty slots are deliberately removed.
                continue
            kept_slots.append(slot)
            by_slot[slot_model.slot_id] = [item.model_dump(mode="json") for item in candidates]
            for poi in candidates:
                current = all_candidates.get(poi.poi_id)
                if current is None or poi.composite_score > current.composite_score:
                    all_candidates[poi.poi_id] = poi
            for item in result.assumptions:
                assumptions.append(
                    Assumption(
                        slot=f"{slot_model.slot_id}:{item.slot}",
                        assumed_value=item.assumed_value,
                        source=item.source,
                        message=item.message,
                    ).model_dump(mode="json")
                )
            relaxed.extend(f"{slot_model.slot_id}:{item}" for item in result.relaxed_constraints)
        updated_blueprints.append(
            ItineraryBlueprint.model_validate(
                {**blueprint.model_dump(mode="json"), "slots": kept_slots}
            ).model_dump(mode="json")
        )

    candidates = sorted(all_candidates.values(), key=lambda item: item.composite_score, reverse=True)
    outcomes = list(job_results.values())
    degraded = bool(missing_required) or any(item[2] for item in outcomes)
    candidate_counts = {slot_id: len(items) for slot_id, items in by_slot.items()}
    update = phase_update(
        "poi_retrieve",
        summary=f"retrieved {len(candidates)} POIs for {len(by_slot)} slots",
        activity_blueprints=updated_blueprints,
        candidate_pois=[item.model_dump(mode="json") for item in candidates],
        candidate_pois_by_slot=by_slot,
        candidate_pois_by_dim={},
        retrieval_meta={
            "mode": "slot",
            "candidate_counts_by_slot": candidate_counts,
            "provider_call_count": provider_calls,
            "provider_query_clause_count": sum(allocations.values()),
            "provider_query_limits": [value for value in allocations.values()],
            "slot_concurrency": max(1, int(settings.poi_slot_concurrency)),
            "sources": sorted(provider_sources),
            "missing_required_slots": missing_required,
            "top_k_per_slot": 8,
            "generation_top_k_per_slot": 4,
        },
        degraded=bool(state.get("degraded")) or degraded,
        tool_calls=[{
            "operation": "poi_search_by_slot",
            "status": "fallback" if degraded else "success",
            "source": ",".join(sorted(provider_sources)) or "none",
            "call_count": provider_calls,
            "query_clause_count": sum(allocations.values()),
            "candidate_counts_by_slot": candidate_counts,
        }],
    )
    update["phase_log"][0].update(
        {
            "candidate_count": len(candidates),
            "candidate_counts_by_slot": candidate_counts,
            "provider_call_count": provider_calls,
            "provider_query_clause_count": sum(allocations.values()),
            "missing_required_slots": missing_required,
            "degraded": degraded,
        }
    )
    if assumptions:
        update["assumptions"] = assumptions
    if relaxed:
        update["relaxed_constraints"] = relaxed
    return update


async def poi_retrieve(state: GraphState) -> dict:
    if state.get("activity_blueprints"):
        return await _retrieve_by_blueprint_slots(state)
    plan = parse_retrieval_plan(state)
    outcome = await PoiSearchTool().run(plan)
    result, source, degraded, cache_hit = (
        outcome.result,
        outcome.source,
        outcome.degraded,
        outcome.cache_hit,
    )
    memory = state.get("memory_context") or {}
    profile = memory.get("user_profile") or {}
    rejected = {
        *{str(poi_id) for poi_id in memory.get("rejected_poi_ids", [])},
        *{str(poi_id) for poi_id in profile.get("avoided_poi_ids", [])},
    }
    liked = {str(poi_id) for poi_id in profile.get("liked_poi_ids", [])}
    if rejected:
        result.pois = [poi for poi in result.pois if poi.poi_id not in rejected]
    for poi in result.pois:
        if poi.poi_id in liked:
            poi.composite_score += 0.15

    log_entry = {
        "phase": "poi_retrieve",
        "status": "completed",
        "ts": utc_now_iso(),
        "summary": f"retrieved {len(result.pois)} POIs",
        "domains": [spec.domain.value for spec in plan.domains],
        "relax_by_domain": {
            meta.domain.value: meta.relax_step for meta in result.by_domain
        },
        "candidate_count": len(result.pois),
        "source": source,
        "degraded": degraded,
        "retrieval_trace": result.retrieval_trace,
    }

    retrieval_meta = {
        "plan": plan.model_dump(mode="json"),
        "by_domain": [item.model_dump(mode="json") for item in result.by_domain],
        "trace": result.retrieval_trace,
        "source": source,
    }

    update: dict = phase_update(
        "poi_retrieve",
        candidate_pois=[p.model_dump(mode="json") for p in result.pois],
        candidate_pois_by_dim=_group_by_dimension(result),
        retrieval_meta=retrieval_meta,
        degraded=bool(state.get("degraded")) or degraded,
        tool_calls=[{
            "operation": "poi_search",
            "status": "fallback" if degraded else "success",
            "source": source,
            "cache_hit": cache_hit,
            "profile_avoided_count": len(rejected),
            "profile_liked_count": len(liked),
        }],
    )
    update["phase_log"] = [log_entry]

    if result.assumptions:
        update["assumptions"] = [a.model_dump(mode="json") for a in result.assumptions]
    if result.relaxed_constraints:
        update["relaxed_constraints"] = result.relaxed_constraints

    return update
