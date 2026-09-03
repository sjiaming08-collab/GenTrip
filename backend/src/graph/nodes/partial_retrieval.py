"""[Replan 3] partial_retrieval — 仅检索 unlocked_slots 需要的 POI。"""

from ...services.poi_retrieval import retrieve_by_plan_async
from ...models.constraints import IntentDomain
from ...services.category_taxonomy import (
    DEFAULT_MEAL_CATEGORIES,
    GENERIC_DINING_TERMS,
    domain_for_category,
)
from ...services.poi_query_parser import parse_retrieval_plan
from ...models.retrieval import DomainSpec, RetrievalPlan, RetrievalFilters
from ..state import GraphState, phase_update

REPLAN_SEARCH_RADIUS_M = 2500


def _anchor_for_slot(stops: list[dict], slot: dict) -> tuple[float | None, float | None]:
    if not stops:
        return None, None
    sequence = int(slot.get("after_seq") or slot.get("sequence") or len(stops))
    index = min(max(sequence - 1, 0), len(stops) - 1)
    stop = stops[index]
    try:
        lat = float(stop.get("lat"))
        lng = float(stop.get("lng"))
    except (TypeError, ValueError):
        return None, None
    return lat, lng


async def partial_retrieval(state: GraphState) -> dict:
    unlocked = state.get("unlocked_slots") or []
    if not unlocked:
        return phase_update("partial_retrieval", replacement_candidates=[])

    candidates: list[dict] = []
    constraints = state.get("constraints") or {}
    geo_scope = state.get("geo_scope") or {}
    current_route = state.get("original_route") or state.get("session_current_route") or {}
    current_stops = current_route.get("stops") or []
    rejected = set()

    # Get rejected POI ids from session
    memory = state.get("memory_context") or {}
    user_profile = memory.get("user_profile") or {}
    for pid in user_profile.get("avoided_poi_ids", []):
        rejected.add(str(pid))
    for pid in memory.get("rejected_poi_ids", []):
        rejected.add(str(pid))

    for slot in unlocked[:4]:  # bound compound replan retrieval fan-out
        target_category = slot.get("new_cuisine") or slot.get("new_category")
        if not target_category:
            continue

        domain = domain_for_category(target_category) or IntentDomain.DINING
        domain_spec = DomainSpec(
            domain=domain,
            categories=(
                list(DEFAULT_MEAL_CATEGORIES)
                if domain == IntentDomain.DINING and target_category in GENERIC_DINING_TERMS
                else [target_category]
            ),
        )
        anchor_lat, anchor_lng = _anchor_for_slot(current_stops, slot)
        filters = RetrievalFilters(
            district=slot.get("new_district") or constraints.get("district"),
            business_area=geo_scope.get("business_area"),
            center_lat=anchor_lat,
            center_lng=anchor_lng,
            radius_m=REPLAN_SEARCH_RADIUS_M if anchor_lat is not None and anchor_lng is not None else None,
            budget_per_person=int(constraints.get("budget_per_person", 150)),
            excluded_categories=constraints.get("excluded_categories") or [],
        )
        plan = RetrievalPlan(
            raw_query=state["user_query"],
            filters=filters,
            domains=[domain_spec],
        )

        result, _source, _degraded, _cache_hit = await retrieve_by_plan_async(plan)
        for poi in result.pois[:6]:  # bounded alternatives for hours and distance validation
            poi_dict = poi.model_dump(mode="json") if hasattr(poi, "model_dump") else poi
            if isinstance(poi_dict, dict) and str(poi_dict.get("poi_id", "")) not in rejected:
                poi_dict["_replan_operation_index"] = slot.get("operation_index", 0)
                poi_dict["slot_id"] = slot.get("slot_id")
                poi_dict["slot_role"] = slot.get("slot_role")
                poi_dict["slot_source"] = slot.get("slot_source")
                poi_dict["slot_time_window"] = slot.get("slot_time_window")
                candidates.append(poi_dict)

    return phase_update(
        "partial_retrieval",
        summary=f"candidates={len(candidates)} slots={len(unlocked)}",
        replacement_candidates=candidates,
    )
