"""Store successful cold-path scores for a later hot-path request."""

from ...services.route_bundle_cache import route_bundle_cache, route_bundle_scope_eligible
from ..state import GraphState, phase_update


async def route_bundle_ingest(state: GraphState) -> dict:
    evaluation = state.get("route_evaluation_meta") or {}
    if not route_bundle_scope_eligible(state):
        return phase_update(
            "route_bundle_ingest",
            summary="bundle skipped: fine-grained or assumed geo scope",
            tool_calls=[{
                "operation": "route_bundle_ingest",
                "source": "local_ttl",
                "status": "skipped",
                "reason": "fine_grained_or_assumed_geo",
            }],
        )
    # LLM scoring may include a user's profile and should not be reused by a
    # different user merely because the route constraints look similar.
    if evaluation.get("source") != "rule":
        return phase_update(
            "route_bundle_ingest",
            summary="bundle skipped: non-deterministic evaluation",
            tool_calls=[{
                "operation": "route_bundle_ingest",
                "source": "local_ttl",
                "status": "skipped",
                "reason": "non_deterministic_evaluation",
            }],
        )

    bundle = await route_bundle_cache.put(state.get("constraints") or {}, state.get("scored_routes") or [])
    return phase_update(
        "route_bundle_ingest",
        summary=f"bundle {'stored=' + bundle.bundle_id if bundle else 'skipped'}",
        tool_calls=[{
            "operation": "route_bundle_ingest",
            "source": "local_ttl",
            "status": "success" if bundle else "skipped",
            "bundle_id": bundle.bundle_id if bundle else None,
        }],
    )
