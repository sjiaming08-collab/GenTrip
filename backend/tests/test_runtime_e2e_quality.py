"""Deterministic runtime acceptance: API-equivalent enqueue -> worker -> persisted result."""

import pytest

from src.runtime.store import MemoryRuntimeStore
from src.runtime.task_queue import QueueFailureResult, QueuedPlanRun
from src.services.plan_service import PlanService
from src.worker import process_message
from tests.golden_conversation_runner import assert_turn, load_golden_cases, route_quality


class InMemoryDurableQueue:
    def __init__(self) -> None:
        self.items: list[QueuedPlanRun] = []
        self.acknowledged: list[str] = []

    async def enqueue(self, initial: dict, session: dict) -> str:
        message_id = f"{len(self.items) + 1}-0"
        self.items.append(QueuedPlanRun(message_id=message_id, initial=initial, session=session))
        return message_id

    async def acknowledge(self, message_id: str) -> None:
        self.acknowledged.append(message_id)

    async def handle_failure(self, _message: QueuedPlanRun, _error: str) -> QueueFailureResult:
        return QueueFailureResult(attempt=1, dead_lettered=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", load_golden_cases(), ids=lambda case: case["id"])
async def test_durable_runtime_preserves_golden_quality_and_operation_trace(monkeypatch, case):
    monkeypatch.setattr("src.services.plan_service.settings.runtime_execution_mode", "redis_stream")
    queue = InMemoryDurableQueue()
    store = MemoryRuntimeStore()
    service = PlanService(store=store, task_queue=queue)
    session_id = f"runtime-e2e-{case['id']}"

    for turn_index, turn in enumerate(case["turns"]):
        started = await service.start_plan(turn["query"], session_id=session_id, idempotency_key=f"{case['id']}-{turn_index}")
        message = queue.items.pop(0)
        assert message.initial["run_id"] == started["run_id"]

        assert await process_message(service, queue, message) is None
        run = await service.get_run(started["run_id"])
        assert run is not None and run["status"] in {"completed", "degraded"}
        state = run["result"]
        assert state is not None
        assert_turn(state, turn["expect"])

        events = await service.get_events_after(started["run_id"], 0)
        phases = [event["phase"] for event in events]
        assert phases[:2] == ["runtime", "runtime"]
        assert "complete" in phases
        checkpoints = await service.list_run_checkpoints(started["run_id"])
        assert checkpoints
        assert queue.acknowledged[-1] == message.message_id

        if turn["expect"].get("quality"):
            quality = route_quality(state, turn["expect"])
            assert quality["expectation_score"] >= turn["expect"]["quality"].get("min_expectation_score", 0)
