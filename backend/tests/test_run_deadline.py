import asyncio

import pytest

from src.config import settings
from src.runtime.events import RuntimeEventBus
from src.runtime.store import MemoryRuntimeStore
from src.services.plan_service import PlanService


class SlowAgent:
    async def astream(self, initial, stream_mode="values"):
        await asyncio.sleep(0.02)
        yield initial


@pytest.mark.asyncio
async def test_run_deadline_becomes_a_terminal_timeout(monkeypatch):
    monkeypatch.setattr(settings, "runtime_run_deadline_seconds", 0.001)
    store = MemoryRuntimeStore()
    service = PlanService(store=store, event_bus=RuntimeEventBus())
    service._agent = SlowAgent()

    state = await service.run_plan("黄浦区吃日料")
    run = await store.get_run("default", state["run_id"])

    assert state["run_status"] == "timed_out"
    assert run["status"] == "timed_out"
    assert run["error_code"] == "run_deadline_exceeded"
