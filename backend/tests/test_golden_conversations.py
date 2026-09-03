import pytest

from src.config import settings
from tests.golden_conversation_runner import load_golden_cases, run_case


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "blueprint_enabled",
    [False, True],
    ids=["legacy", "blueprint"],
)
@pytest.mark.parametrize("case", load_golden_cases(), ids=lambda case: case["id"])
async def test_golden_conversation(case, blueprint_enabled, monkeypatch):
    monkeypatch.setattr(settings, "planner_blueprint_enabled", blueprint_enabled)
    await run_case(case)
