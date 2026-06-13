"""[2] poi_retrieve — 按约束召回候选 POI。"""

from ...mocks.poi_store import retrieve_pois
from ..state import GraphState, phase_update


async def poi_retrieve(state: GraphState) -> dict:
    constraints = state["constraints"]
    assert constraints is not None

    pois = retrieve_pois(district=constraints["district"], limit=10)
    if not pois:
        pois = retrieve_pois(limit=10)

    return phase_update(
        "poi_retrieve",
        candidate_pois=[p.model_dump(mode="json") for p in pois],
    )
