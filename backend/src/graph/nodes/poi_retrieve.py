"""[2] poi_retrieve — 用户提问 → 多意图域 POI 检索。"""

from ...models.retrieval import RetrievalResult
from ...services.poi_query_parser import parse_retrieval_plan
from ...services.poi_retrieval import retrieve_by_plan_async
from ..state import GraphState, phase_update, utc_now_iso


def _group_by_dimension(result: RetrievalResult) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for poi in result.pois:
        key = poi.dimension or "unknown"
        grouped.setdefault(key, []).append(poi.model_dump(mode="json"))
    return grouped


async def poi_retrieve(state: GraphState) -> dict:
    plan = parse_retrieval_plan(state)
    result, source, degraded, cache_hit = await retrieve_by_plan_async(plan)
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
