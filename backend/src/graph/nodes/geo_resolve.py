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

    resolved_constraints = dict(constraints)
    district_corrected = bool(
        scope.district
        and scope.source != "default"
        and scope.confidence >= 0.7
        and scope.district != constraints.get("district")
    )
    if district_corrected:
        resolved_constraints["district"] = scope.district

    update = phase_update(
        "geo_resolve",
        summary=f"scope={scope.scope_type}:{scope.resolved_name}",
        geo_scope=scope.model_dump(mode="json"),
        constraints=resolved_constraints,
    )
    update["phase_log"][0].update({
        "scope_type": scope.scope_type,
        "resolved_name": scope.resolved_name,
        "source": scope.source,
    })
    if district_corrected:
        update["assumptions"] = [{
            "slot": "district",
            "assumed_value": str(scope.district),
            "source": scope.source,
            "message": f"根据地点“{scope.resolved_name}”定位到{scope.district}",
            "overridable": True,
        }]
    elif scope.assumptions:
        update["assumptions"] = [item.model_dump(mode="json") for item in scope.assumptions]
    return update
