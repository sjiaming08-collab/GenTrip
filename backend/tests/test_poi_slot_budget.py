import asyncio

import pytest

from src.config import settings
from src.graph.nodes import poi_retrieve as poi_retrieve_module
from src.graph.nodes.poi_retrieve import _allocate_slot_query_limits, poi_retrieve
from src.graph.state import build_initial_state
from src.models.retrieval import RetrievalResult
from src.services.planner_tools import PoiSearchOutcome


def test_slot_query_allocator_prioritizes_required_slots_and_respects_budgets(monkeypatch):
    monkeypatch.setattr(settings, "poi_queries_per_run", 5)
    monkeypatch.setattr(settings, "poi_queries_per_slot", 2)
    jobs = [
        (("optional",), 4, False),
        (("required-a",), 4, True),
        (("required-b",), 1, True),
    ]

    allocated = _allocate_slot_query_limits(jobs)

    assert sum(allocated.values()) == 5
    assert max(allocated.values()) == 2
    assert allocated[("required-a",)] >= 1
    assert allocated[("required-b",)] == 1


@pytest.mark.asyncio
async def test_slot_retrieval_runs_independent_signatures_with_bounded_parallelism(monkeypatch):
    inflight = 0
    peak_inflight = 0
    calls = 0

    class FakePoiSearchTool:
        async def run(self, plan, *, limit=20):
            nonlocal inflight, peak_inflight, calls
            calls += 1
            inflight += 1
            peak_inflight = max(peak_inflight, inflight)
            await asyncio.sleep(0.02)
            inflight -= 1
            return PoiSearchOutcome(RetrievalResult(pois=[], plan=plan), "fixture", False, False)

    monkeypatch.setattr(poi_retrieve_module, "PoiSearchTool", FakePoiSearchTool)
    monkeypatch.setattr(settings, "poi_slot_parallel_enabled", True)
    monkeypatch.setattr(settings, "poi_slot_concurrency", 2)
    monkeypatch.setattr(settings, "poi_queries_per_run", 16)
    state = build_initial_state("杭州文化散步")
    state["constraints"] = {
        "raw_query": state["user_query"],
        "domains": ["sightseeing"],
        "city": "杭州市",
        "budget_per_person": 200,
        "time_budget_minutes": 180,
        "poi_count": 3,
    }
    state["activity_blueprints"] = [{
        "blueprint_id": "bp-1",
        "style": "balanced",
        "scene_type": "couple",
        "start_at": "10:00",
        "return_by": "13:00",
        "slots": [
            {"slot_id": "s1", "role": "anchor", "domain": "sightseeing", "categories": ["公园"], "duration_minutes": 60},
            {"slot_id": "s2", "role": "anchor", "domain": "sightseeing", "categories": ["博物馆"], "duration_minutes": 60},
            {"slot_id": "s3", "role": "optional", "required": False, "domain": "shopping", "categories": ["购物"], "duration_minutes": 45},
        ],
    }]

    update = await poi_retrieve(state)

    assert calls == 3
    assert peak_inflight == 2
    assert update["retrieval_meta"]["provider_query_clause_count"] <= 16
    assert update["retrieval_meta"]["slot_concurrency"] == 2
