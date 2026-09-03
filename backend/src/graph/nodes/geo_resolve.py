"""[2] geo_resolve — natural-language place mentions -> GeoScope."""

from ...services.planner_tools import GeoResolveTool
from ..state import GraphState, phase_update


async def geo_resolve(state: GraphState) -> dict:
    constraints = state.get("constraints") or {}
    scope = await GeoResolveTool().run(
        state["user_query"],
        location_mentions=constraints.get("location_mentions"),
        user_lat=state.get("user_lat"),
        user_lng=state.get("user_lng"),
        city=constraints.get("city"),
        district=constraints.get("district"),
    )

    resolved_constraints = dict(constraints)
    geo_resolved = scope.source != "default" and scope.confidence >= 0.7
    city_corrected = bool(geo_resolved and scope.city and scope.city != constraints.get("city"))
    district_corrected = bool(geo_resolved and scope.district and scope.district != constraints.get("district"))
    if city_corrected:
        resolved_constraints["city"] = scope.city
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
        "coord_system": scope.coord_system,
    })
    if city_corrected or district_corrected:
        update["assumptions"] = []
        if city_corrected:
            update["assumptions"].append({
                "slot": "city",
                "assumed_value": str(scope.city),
                "source": scope.source,
                "message": f"根据地点定位到{scope.city}",
                "overridable": True,
            })
        if district_corrected:
            update["assumptions"].append({
                "slot": "district",
                "assumed_value": str(scope.district),
                "source": scope.source,
                "message": f"根据地点定位到{scope.district}",
                "overridable": True,
            })
    elif scope.assumptions:
        update["assumptions"] = [item.model_dump(mode="json") for item in scope.assumptions]
    return update
