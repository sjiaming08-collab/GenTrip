import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "evaluate_route_plans.py"


@pytest.mark.asyncio
async def test_route_eval_uses_isolated_runtime_and_disables_live_llm(monkeypatch):
    spec = importlib.util.spec_from_file_location("route_eval_runner", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    monkeypatch.setattr(module.settings, "llm_enabled", True)
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
