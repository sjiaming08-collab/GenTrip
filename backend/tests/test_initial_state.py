from src.graph.state import build_initial_state


def test_initial_state_has_all_keys():
    state = build_initial_state("附近有什么好玩的")
    required = [
        "run_id",
        "run_status",
        "user_query",
        "assumptions",
        "candidate_pois",
        "candidate_routes",
        "valid_routes",
        "scored_routes",
        "route_results",
        "phase_log",
    ]
    for key in required:
        assert key in state
    assert state["run_status"] == "running"
    assert state["assumptions"] == []
