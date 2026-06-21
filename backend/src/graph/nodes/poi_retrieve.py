"""[2] poi_retrieve — 用户提问 → 多意图域 POI 检索。"""

from ...models.retrieval import RetrievalResult
from ...services.poi_query_parser import parse_retrieval_plan
from ...services.poi_retrieval import retrieve_by_plan
from ..state import GraphState, phase_update, utc_now_iso


def _group_by_dimension(result: RetrievalResult) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for poi in result.pois:
        key = poi.dimension or "unknown"
        grouped.setdefault(key, []).append(poi.model_dump(mode="json"))
    return grouped


async def poi_retrieve(state: GraphState) -> dict:
    plan = parse_retrieval_plan(state)
    result = retrieve_by_plan(plan)

    log_entry = {
        "phase": "poi_retrieve",
        "ts": utc_now_iso(),
        "domains": [spec.domain.value for spec in plan.domains],
        "relax_by_domain": {
            meta.domain.value: meta.relax_step for meta in result.by_domain
        },
        "candidate_count": len(result.pois),
    }

    retrieval_meta = {
        "plan": plan.model_dump(mode="json"),
        "by_domain": [item.model_dump(mode="json") for item in result.by_domain],
    }

    update: dict = phase_update(
        "poi_retrieve",
        candidate_pois=[p.model_dump(mode="json") for p in result.pois],
        candidate_pois_by_dim=_group_by_dimension(result),
        retrieval_meta=retrieval_meta,
    )
    update["phase_log"] = [log_entry]

    if result.assumptions:
        update["assumptions"] = [a.model_dump(mode="json") for a in result.assumptions]
    if result.relaxed_constraints:
        update["relaxed_constraints"] = result.relaxed_constraints

    return update
