import pytest

from src.graph.nodes.geo_resolve import geo_resolve
from src.graph.state import build_initial_state
from src.services.poi_query_parser import parse_retrieval_plan


@pytest.mark.asyncio
async def test_geo_resolve_node_writes_scope():
    state = build_initial_state("武康路附近咖啡")

    update = await geo_resolve(state)

    assert update["current_phase"] == "geo_resolve"
    assert update["geo_scope"]["business_area"] == "武康路/安福路"
    assert update["geo_scope"]["district"] == "徐汇区"
    assert update["geo_scope"]["center_lat"] is not None


def test_parse_retrieval_plan_prefers_geo_scope():
    state = build_initial_state("附近找个咖啡", user_lat=31.22, user_lng=121.45)
    state["constraints"] = {
        "domains": ["dining"],
        "district": "徐汇区",
        "budget_per_person": 80,
    }
    state["geo_scope"] = {
        "scope_type": "nearby",
        "center_lat": 31.22,
        "center_lng": 121.45,
        "radius_m": 1500,
        "source": "user_location",
    }

    plan = parse_retrieval_plan(state)

    assert plan.filters.district is None
    assert plan.filters.center_lat == 31.22
    assert plan.filters.center_lng == 121.45
    assert plan.filters.radius_m == 1500
    assert plan.filters.budget_per_person == 80
