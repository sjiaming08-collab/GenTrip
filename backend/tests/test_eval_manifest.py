import json
from pathlib import Path


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_eval_manifest_references_existing_versioned_suites():
    manifest = json.loads((FIXTURES / "eval_manifest.json").read_text(encoding="utf-8"))

    assert manifest["version"]
    assert manifest["hard_constraint_policy"] == "zero_tolerance"
    assert manifest["quality_gate"]["minimum_case_pass_rate"] == 1.0
    assert manifest["quality_gate"]["zero_hard_constraint_violations"] is True
    assert manifest["llm_judge"]["mode"] == "offline"
    assert manifest["local_life_agents"] == 10
    assert manifest["local_life_single_cases"] == 120
    assert manifest["local_life_conversation_turns"] == 30
    assert manifest["local_life_quality_gate"]["minimum_single_end_to_end_pass_rate"] == 0.9
    for key in (
        "constraint_suite",
        "conversation_suite",
        "route_suite",
        "local_life_suite",
        "poi_fixture",
    ):
        assert (FIXTURES / manifest[key]).is_file()
