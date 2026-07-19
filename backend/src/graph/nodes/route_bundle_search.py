"""RouteBundle hot-path lookup after constraint extraction."""

from ...services.route_bundle_cache import route_bundle_cache, route_bundle_scope_eligible
from ..state import GraphState, phase_update


async def route_bundle_search(state: GraphState) -> dict:
    constraints = state.get("constraints") or {}
    memory = state.get("memory_context") or {}
    profile = memory.get("user_profile") or {}
    has_poi_preferences = bool(
        memory.get("rejected_poi_ids")
        or profile.get("avoided_poi_ids")
        or profile.get("liked_poi_ids")
    )
    # Bundles are precomputed from district-level routes. Current-location
    # requests require a fresh cold path because the user position is dynamic.
    if has_poi_preferences:
        bundle = None
        reason = "poi_preferences"
    elif state.get("user_lat") is not None and state.get("user_lng") is not None:
        bundle = None
        reason = "user_location"
    elif not route_bundle_scope_eligible(state):
        bundle = None
        reason = "fine_grained_or_assumed_geo"
    else:
        bundle = await route_bundle_cache.get(constraints)
        reason = "hit" if bundle else "miss"

    if bundle is None:
        update = phase_update(
            "route_bundle_search",
            summary=f"bundle {reason}",
            plan_path="cold",
            bundle_candidates=[],
            bundle_match_score=0.0,
            matched_bundle_id=None,
            tool_calls=[{"operation": "route_bundle_search", "source": "local_ttl", "status": "miss", "reason": reason}],
        )
    else:
        routes = [item.get("route") for item in bundle.scored_routes if item.get("route")]
        update = phase_update(
            "route_bundle_search",
            summary=f"bundle hit={bundle.bundle_id} score={bundle.match_score:.2f} routes={len(routes)}",
            plan_path="hot",
            bundle_candidates=[{"bundle_id": bundle.bundle_id, "scored_routes": bundle.scored_routes, "match_score": bundle.match_score}],
            bundle_match_score=bundle.match_score,
            matched_bundle_id=bundle.bundle_id,
            candidate_routes=routes,
            tool_calls=[{"operation": "route_bundle_search", "source": bundle.source, "status": "success", "cache_hit": True, "bundle_id": bundle.bundle_id, "match_score": bundle.match_score, "match_type": "exact" if bundle.match_score == 1.0 else "similarity"}],
        )
    update["phase_log"][0].update({"bundle_match_score": update.get("bundle_match_score", 0.0)})
    return update
