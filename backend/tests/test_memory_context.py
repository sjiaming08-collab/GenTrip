import pytest

from src.graph.state import build_initial_state
from src.models.session import SessionState
from src.services.constraint_rules import rule_based_extract
from src.services.plan_service import PlanService


def test_rule_extract_fills_missing_constraints_from_memory_context():
    state = build_initial_state("换一家咖啡")
    state["memory_context"] = {
        "session_id": "s1",
        "current_constraints": {
            "district": "静安区",
            "budget_per_person": 100,
            "time_budget_minutes": 120,
            "preferred_cuisines": ["日料"],
        },
        "assumptions": [],
        "recent_turns": [],
    }

    constraints, assumptions = rule_based_extract(state)

    assert constraints.district == "静安区"
    assert constraints.budget_per_person == 100
    assert constraints.time_budget_minutes == 120
    assert constraints.preferred_cuisines == ["咖啡"]
    assert any(item.source == "session_memory" for item in assumptions)


def test_explicit_memory_fact_overrides_an_old_constraint_value():
    state = build_initial_state("想吃日料")
    state["memory_context"] = {
        "session_id": "s1",
        "current_constraints": {"budget_per_person": 150},
        "memory_facts": [{"slot": "budget_per_person", "value": 100, "source": "explicit_user"}],
        "assumptions": [],
        "recent_turns": [],
    }

    constraints, _ = rule_based_extract(state)

    assert constraints.budget_per_person == 100


def test_explicit_memory_facts_are_traced_and_expire():
    facts = PlanService._explicit_memory_facts("黄浦区，人均100元，3小时", "turn-1")

    assert {fact["slot"] for fact in facts} >= {"district", "budget_per_person", "time_budget_minutes"}
    assert all(fact["source"] == "explicit_user" and fact["confidence"] == "high" for fact in facts)
    assert PlanService._active_memory_facts(facts)


@pytest.mark.asyncio
async def test_plan_service_injects_saved_constraints_into_next_turn():
    service = PlanService()
    session_id = "memory-flow-001"
    session = SessionState(
        session_id=session_id,
        current_constraints={
            "district": "静安区",
            "budget_per_person": 100,
            "time_budget_minutes": 120,
            "domains": ["dining", "sightseeing"],
        },
        dialog_summary="用户上一轮在静安区规划了日料逛吃路线，预算人均100元，时长2小时。",
    )
    service._sessions[session_id] = session

    second = await service.run_plan("换一家咖啡", session_id=session_id)

    assert second["constraints"]["district"] == "静安区"
    assert second["constraints"]["budget_per_person"] == 100
    assert second["constraints"]["time_budget_minutes"] == 120
    saved = service.get_session(session_id)
    assert saved is not None
    assert saved.current_constraints is not None
    assert saved.dialog_summary
