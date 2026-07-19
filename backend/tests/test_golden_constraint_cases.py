"""Declarative language-variation gate for deterministic constraint extraction."""

import json
from pathlib import Path

import pytest

from src.graph.state import build_initial_state
from src.services.constraint_rules import rule_based_extract


CASES_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "golden_constraint_cases.json"
CASES = json.loads(CASES_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_golden_constraint_case(case):
    state = build_initial_state(case["query"])
    if case.get("memory"):
        state["memory_context"] = {"current_constraints": case["memory"]}

    constraints, _assumptions = rule_based_extract(state)
    actual = constraints.model_dump(mode="json")
    for field, expected in case["expect"].items():
        assert actual[field] == expected, {"id": case["id"], "field": field, "actual": actual[field]}
