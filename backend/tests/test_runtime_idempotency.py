import asyncio

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


@pytest.mark.asyncio
async def test_first_turn_idempotency_reuses_generated_session() -> None:
    service = PlanService(store=MemoryRuntimeStore())

    first = await service.start_plan("first request", idempotency_key="first-turn-key")
    second = await service.start_plan("first request", idempotency_key="first-turn-key")

    assert second == first
    assert len(service._store.runs) == 1
    await service._tasks[first["run_id"]]


@pytest.mark.asyncio
async def test_idempotency_key_is_isolated_by_tenant() -> None:
    service = PlanService(store=MemoryRuntimeStore())

    alpha = await service.start_plan("same payload", tenant_id="alpha", idempotency_key="shared-key")
    beta = await service.start_plan("same payload", tenant_id="beta", idempotency_key="shared-key")

    assert alpha != beta
    tasks = [service._tasks[alpha["run_id"]], service._tasks[beta["run_id"]]]
    await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_concurrent_first_turn_retries_create_one_run() -> None:
    service = PlanService(store=MemoryRuntimeStore())
    first, second = await asyncio.gather(
        service.start_plan("concurrent request", idempotency_key="concurrent-key"),
        service.start_plan("concurrent request", idempotency_key="concurrent-key"),
    )

    assert first == second
    assert len(service._store.runs) == 1
    await service._tasks[first["run_id"]]
