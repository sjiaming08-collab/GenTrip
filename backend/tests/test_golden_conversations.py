import pytest

from tests.golden_conversation_runner import load_golden_cases, run_case


@pytest.mark.asyncio
@pytest.mark.parametrize("case", load_golden_cases(), ids=lambda case: case["id"])
async def test_golden_conversation(case):
    await run_case(case)
