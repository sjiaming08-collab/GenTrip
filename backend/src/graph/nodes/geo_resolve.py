"""[2] geo_resolve — natural-language place mentions -> GeoScope."""

from ...services.geo_resolver import GeoResolver
from ..state import GraphState, phase_update


async def geo_resolve(state: GraphState) -> dict:
    # Use constraints.district (from query or memory) as fallback instead of hardcoded default
    constraints = state.get("constraints") or {}
    memory_district = constraints.get("district", "")
    default_district = memory_district if memory_district in {"徐汇区", "静安区", "浦东新区", "黄浦区"} else "徐汇区"

    resolver = GeoResolver(default_district=default_district)
    scope = await resolver.resolve_geo_scope(
        state["user_query"],
        user_lat=state.get("user_lat"),
        user_lng=state.get("user_lng"),
    )

    update = phase_update(
        "geo_resolve",
        summary=f"scope={scope.scope_type}:{scope.resolved_name}",
        geo_scope=scope.model_dump(mode="json"),
    )
    update["phase_log"][0].update({
        "scope_type": scope.scope_type,
        "resolved_name": scope.resolved_name,
        "source": scope.source,
    })
    if scope.assumptions:
        update["assumptions"] = [item.model_dump(mode="json") for item in scope.assumptions]
    return update
