from src.graph.nodes.planning_decision import assess_planning_feasibility
from src.graph.state import build_initial_state


def _state(*, duration: int, domains: list[str]):
    state = build_initial_state("测试路线")
    state["constraints"] = {
        "district": "黄浦区",
        "domains": domains,
        "time_budget_minutes": duration,
        "budget_per_person": 150,
    }
    state["geo_scope"] = {"scope_type": "district", "resolved_name": "黄浦区"}
    return state


def test_preflight_rejects_only_when_optimistic_estimate_exceeds_available_time():
    decision = assess_planning_feasibility(_state(duration=50, domains=["dining", "sightseeing"]))

    assert decision.status == "infeasible"
    assert decision.estimate.optimistic_minutes > 50


def test_preflight_keeps_uncertain_local_estimate_on_the_retrieval_path():
    decision = assess_planning_feasibility(_state(duration=180, domains=["dining", "sightseeing"]))

    assert decision.status == "marginal"
    assert decision.outcome == "marginal"
    assert decision.estimate.optimistic_minutes <= 180
    assert decision.estimate.conservative_minutes > 180


def test_preflight_marks_route_ready_when_conservative_estimate_fits():
    decision = assess_planning_feasibility(_state(duration=300, domains=["dining", "sightseeing"]))

    assert decision.status == "ready"
    assert decision.outcome == "route_ready"
