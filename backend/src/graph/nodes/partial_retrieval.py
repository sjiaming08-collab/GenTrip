"""[Replan 3] partial_retrieval — 仅检索 unlocked_slots 需要的 POI。"""

from ...services.poi_retrieval import retrieve_by_plan
from ...services.poi_query_parser import parse_retrieval_plan
from ...models.retrieval import DomainSpec, RetrievalPlan, RetrievalFilters
from ..state import GraphState, phase_update


async def partial_retrieval(state: GraphState) -> dict:
    unlocked = state.get("unlocked_slots") or []
    if not unlocked:
        return phase_update("partial_retrieval", replacement_candidates=[])

    candidates: list[dict] = []
    constraints = state.get("constraints") or {}
    geo_scope = state.get("geo_scope") or {}
    rejected = set()

    # Get rejected POI ids from session
    memory = state.get("memory_context") or {}
    user_profile = memory.get("user_profile") or {}
    for pid in user_profile.get("avoided_poi_ids", []):
        rejected.add(str(pid))
    for pid in memory.get("rejected_poi_ids", []):
        rejected.add(str(pid))

    for slot in unlocked[:2]:  # max 2 slots
        cuisine = slot.get("new_cuisine")
        if not cuisine:
            continue

        # Build a minimal RetrievalPlan for just this cuisine
        domain_spec = DomainSpec(
            domain="dining",
            categories=[cuisine] if cuisine else None,
        )
        filters = RetrievalFilters(
            district=slot.get("new_district") or constraints.get("district"),
            business_area=geo_scope.get("business_area"),
            budget_per_person=int(constraints.get("budget_per_person", 150)),
            excluded_categories=constraints.get("excluded_categories") or [],
        )
        plan = RetrievalPlan(
            raw_query=state["user_query"],
            filters=filters,
            domains=[domain_spec],
        )

        result = retrieve_by_plan(plan)
        for poi in result.pois[:3]:  # top 3 per slot
            poi_dict = poi.model_dump(mode="json") if hasattr(poi, "model_dump") else poi
            if isinstance(poi_dict, dict) and str(poi_dict.get("poi_id", "")) not in rejected:
                candidates.append(poi_dict)

    return phase_update(
        "partial_retrieval",
        summary=f"candidates={len(candidates)} slots={len(unlocked)}",
        replacement_candidates=candidates,
    )
