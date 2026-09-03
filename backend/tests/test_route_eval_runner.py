import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "evaluate_route_plans.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("route_eval_runner", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_route_eval_uses_isolated_runtime_and_disables_live_llm(monkeypatch):
    module = _load_module()

    monkeypatch.setattr(module.settings, "llm_enabled", True)
    monkeypatch.setattr(module.settings, "redis_url", "redis://should-not-be-used")
    monkeypatch.setattr(module.settings, "database_url", "postgresql://should-not-be-used")
    monkeypatch.setattr(module.settings, "poi_provider", "amap")
    results = await module.run_cases(
        [
            {
                "id": "nearby_coffee_after_hours",
                "query": "徐家汇附近喝咖啡，人均80元",
                "user_lat": 31.196,
                "user_lng": 121.438,
                "expect": {"domains": ["dining"], "categories": ["咖啡"], "min_stops": 1},
                "min_quality_score": 0.7,
            }
        ]
    )

    assert results[0]["passed"] is True
    assert module.settings.llm_enabled is True
    assert module.settings.redis_url == "redis://should-not-be-used"
    assert module.settings.database_url == "postgresql://should-not-be-used"
    assert module.settings.poi_provider == "amap"


def test_independent_legality_checks_start_exclusions_and_district():
    module = _load_module()
    state = {
        "constraints": {
            "start_at": "14:00",
            "district": "黄浦区",
            "excluded_categories": ["博物馆"],
        },
        "candidate_pois": [{"poi_id": "p1", "district": "徐汇区"}],
    }
    route = {
        "stops": [{
            "sequence": 1,
            "poi_id": "p1",
            "poi_name": "历史博物馆",
            "category": "博物馆",
            "arrival_time": "13:30",
            "departure_time": "15:00",
            "travel_time_from_prev_min": 0,
        }]
    }

    violations = module.independent_legal_violations(state, route)

    assert any(item.startswith("start_time_violated") for item in violations)
    assert any(item.startswith("excluded_poi") for item in violations)
    assert any(item.startswith("district_mismatch") for item in violations)


def test_independent_legality_only_treats_compiled_hard_budget_as_violation():
    module = _load_module()
    route = {"estimated_cost_per_person": 182, "stops": []}
    policy_state = {
        "constraints": {"budget_per_person": 180},
        "compiled_constraints": {
            "atoms": [{"field": "budget_per_person", "strength": "policy"}],
        },
    }
    hard_state = {
        **policy_state,
        "compiled_constraints": {
            "atoms": [{"field": "budget_per_person", "strength": "hard"}],
        },
    }

    assert not any(
        item.startswith("cost_over_budget")
        for item in module.independent_legal_violations(policy_state, route)
    )
    assert any(
        item.startswith("cost_over_budget")
        for item in module.independent_legal_violations(hard_state, route)
    )


@pytest.mark.asyncio
async def test_expanded_route_eval_golden_suite_passes():
    module = _load_module()
    cases = module.load_cases(module.DEFAULT_CASES)

    results = await module.run_cases(cases)

    failures = {item["id"]: item["issues"] for item in results if not item["passed"]}
    assert not failures
    assert len(results) >= 30


@pytest.mark.asyncio
async def test_expanded_route_eval_golden_suite_passes_with_blueprints():
    module = _load_module()
    cases = module.load_cases(module.DEFAULT_CASES)

    results = await module.run_cases(cases, blueprint_enabled=True)

    failures = {item["id"]: item["issues"] for item in results if not item["passed"]}
    assert not failures
    assert len(results) >= 30
