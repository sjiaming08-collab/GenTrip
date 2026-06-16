"""[2] poi_retrieve — 按约束召回候选 POI。"""

from ...mocks.poi_store import retrieve_pois_with_meta
from ..state import GraphState, phase_update, utc_now_iso


async def poi_retrieve(state: GraphState) -> dict:
    constraints = state["constraints"]
    assert constraints is not None

    result = retrieve_pois_with_meta(
        district=constraints.get("district"),
        limit=10,
        purpose=constraints.get("purpose"),
        preferred_cuisines=constraints.get("preferred_cuisines"),
        activity_tags=constraints.get("activity_tags"),
        budget_per_person=constraints.get("budget_per_person"),
    )

    log_entry = {
        "phase": "poi_retrieve",
        "ts": utc_now_iso(),
        "relax_step": result.relax_step,
        "final_leaves": result.final_leaves,
        "candidate_count": len(result.pois),
    }

    update: dict = phase_update(
        "poi_retrieve",
        candidate_pois=[p.model_dump(mode="json") for p in result.pois],
    )
    update["phase_log"] = [log_entry]

    if result.assumptions:
        update["assumptions"] = [a.model_dump(mode="json") for a in result.assumptions]
    if result.relax_step != "R0":
        update["relaxed_constraints"] = [result.relax_step]

    return update
