import pytest

from src.config import settings
from src.graph.nodes import constraint_extract as constraint_node_module
from src.graph.nodes import route_evaluate as route_evaluate_module
from src.graph.state import build_initial_state
from src.models.constraints import Constraints, IntentDomain
from src.models.session import SessionState, Turn
from src.runtime.session_summary_queue import QueuedSessionSummary
from src.runtime.store import MemoryRuntimeStore
from src.services.plan_service import PlanService


def _route(name: str, poi_id: str) -> dict:
    return {
        "plan_id": name,
        "plan_name": name,
        "summary": name,
        "stops": [{
            "sequence": 1,
            "poi_id": poi_id,
            "poi_name": poi_id,
            "category": "park",
            "arrival_time": "14:00",
            "departure_time": "15:00",
            "visit_duration_min": 60,
        }],
        "total_duration_min": 60,
        "estimated_cost_per_person": 20,
    }


@pytest.mark.asyncio
async def test_fused_constraint_decision_can_reject_a_cold_turn(monkeypatch):
    async def fused_extract(_state):
        return (
            Constraints(
                raw_query="explain a programming concept",
                domains=[IntentDomain.SIGHTSEEING],
                district="徐汇区",
                time_budget_minutes=180,
                budget_per_person=100,
                poi_count=3,
            ),
            [],
            {
                "operation": "constraint_extract",
                "status": "success",
                "turn_decision": {
                    "turn_mode": "reject",
                    "primary_intent": "non_travel",
                    "query_understanding": "programming question",
                },
            },
        )

    monkeypatch.setattr(constraint_node_module, "extract_with_meta", fused_extract)
    state = build_initial_state("explain a programming concept")

    update = await constraint_node_module.constraint_extract(state)

    assert update["turn_mode"] == "reject"
    assert update["route_intent"]["intent_type"] == "non_travel"


@pytest.mark.asyncio
async def test_route_evaluate_sends_every_valid_route_to_llm(monkeypatch):
    captured: list[str] = []

    async def score_all(routes, **_kwargs):
        captured.extend(route.plan_id for route in routes)
        return {}, {"operation": "route_evaluate", "status": "success"}

    monkeypatch.setattr(settings, "route_evaluate_mode", "llm_with_fallback")
    monkeypatch.setattr(route_evaluate_module, "llm_score_routes_with_meta", score_all)
    state = build_initial_state("quiet afternoon route")
    state.update({
        "constraints": {
            "budget_per_person": 100,
            "time_budget_minutes": 180,
            "domains": ["sightseeing"],
            "preferred_cuisines": None,
        },
        "valid_routes": [_route("r1", "p1"), _route("r2", "p2"), _route("r3", "p3")],
        "candidate_pois": [
            {"poi_id": "p1", "rating": 4.0, "dimension": "sightseeing"},
            {"poi_id": "p2", "rating": 4.2, "dimension": "sightseeing"},
            {"poi_id": "p3", "rating": 4.5, "dimension": "sightseeing"},
        ],
    })

    await route_evaluate_module.route_evaluate(state)

    assert captured == ["r1", "r2", "r3"]


def _turn(turn_id: str, query: str) -> Turn:
    return Turn(turn_id=turn_id, user_query=query, reply_type="route")


@pytest.mark.asyncio
async def test_background_summary_updates_matching_session_version(monkeypatch):
    store = MemoryRuntimeStore()
    service = PlanService(store=store)
    session = SessionState(session_id="summary-session", recent_turns=[_turn("t1", "first")])
    await service.save_session(session)

    async def summarize(_session):
        return "LLM summary", {
            "operation": "session_summary",
            "status": "success",
            "model": "test-model",
        }

    monkeypatch.setattr("src.services.plan_service.summarize_session_with_meta", summarize)
    job = QueuedSessionSummary("m1", "default", session.session_id, "t1", "run1")

    requeue = await service.execute_session_summary(job)
    saved = await service.load_session(session.session_id)

    assert requeue is None
    assert saved is not None
    assert saved.dialog_summary == "LLM summary"
    assert saved.dialog_summary_turn_id == "t1"


@pytest.mark.asyncio
async def test_background_summary_does_not_overwrite_a_newer_turn(monkeypatch):
    store = MemoryRuntimeStore()
    service = PlanService(store=store)
    session = SessionState(session_id="summary-conflict", recent_turns=[_turn("t1", "first")])
    await service.save_session(session)

    async def summarize(_snapshot):
        current = await service.load_session(session.session_id)
        assert current is not None
        current.add_turn(_turn("t2", "second"))
        await service.save_session(current)
        return "stale summary", {"operation": "session_summary", "status": "success"}

    monkeypatch.setattr("src.services.plan_service.summarize_session_with_meta", summarize)
    job = QueuedSessionSummary("m1", "default", session.session_id, "t1", "run1")

    requeue = await service.execute_session_summary(job)
    saved = await service.load_session(session.session_id)

    assert requeue == "t2"
    assert saved is not None
    assert saved.dialog_summary != "stale summary"
    assert saved.dialog_summary_turn_id is None
