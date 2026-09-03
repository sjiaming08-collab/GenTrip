"""Shape and coverage contract for the repository Golden Sets."""

import json
from pathlib import Path


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _load(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _assert_unique_ids(cases: list[dict]) -> None:
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids))


def test_golden_set_size_and_identity_contract() -> None:
    constraints = _load("golden_constraint_cases.json")
    conversations = _load("golden_conversations.json")
    routes = _load("route_eval_cases.json")

    assert len(constraints) >= 80
    assert len(conversations) >= 40
    assert sum(len(case["turns"]) for case in conversations) >= 150
    assert len(routes) >= 30
    for cases in (constraints, conversations, routes):
        _assert_unique_ids(cases)
    assert all(turn.get("expect") for case in conversations for turn in case["turns"])


def test_golden_set_contains_edge_and_resilience_coverage() -> None:
    constraints = _load("golden_constraint_cases.json")
    conversations = _load("golden_conversations.json")
    routes = _load("route_eval_cases.json")

    constraint_ids = {case["id"] for case in constraints}
    conversation_text = " ".join(turn["query"] for case in conversations for turn in case["turns"])
    fault_cases = [case for case in routes if (case.get("simulate") or {}).get("travel_time_http_failure")]

    assert any(case_id.startswith("edge_time_") for case_id in constraint_ids)
    assert any(case_id.startswith("multi_exclusion_") for case_id in constraint_ids)
    assert any(case_id.startswith("rare_preference_") for case_id in constraint_ids)
    for keyword in ("换成", "再加", "去掉", "不想", "取消", "重新规划"):
        assert keyword in conversation_text
    assert any(
        turn.get("action") == "cancel_run"
        for case in conversations
        for turn in case["turns"]
    )
    assert len(fault_cases) >= 4
    assert all("travel_time" in case["expect"]["required_tool_fallbacks"] for case in fault_cases)
