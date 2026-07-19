import pytest

from src.runtime.store import MemoryRuntimeStore
from src.services.plan_service import PlanService


@pytest.mark.asyncio
async def test_async_plan_start_reuses_idempotency_key() -> None:
    service = PlanService(store=MemoryRuntimeStore())

    first = await service.start_plan("徐汇逛吃", session_id="idempotent-session", idempotency_key="same-request")
    second = await service.start_plan("徐汇逛吃", session_id="idempotent-session", idempotency_key="same-request")

    assert second == first
    await service._tasks[first["run_id"]]
