import pytest

from src.config import settings
from src.api.container import plan_service as app_plan_service
from src.runtime.store import MemoryRuntimeStore
from src.runtime.task_queue import QueueFailureResult, QueueUnavailable, QueuedPlanRun
from src.services.plan_service import PlanService, QueuedRunFailed
from src.worker import process_message


class FakeQueue:
    def __init__(self):
        self.items: list[tuple[dict, dict]] = []

    async def enqueue(self, initial: dict, session: dict) -> str:
        self.items.append((initial, session))
        return "1-0"


class FailingQueue:
    async def enqueue(self, initial: dict, session: dict) -> str:
        raise QueueUnavailable("redis unavailable")


class WorkerQueue:
    def __init__(self, failures: list[QueueFailureResult]):
        self.failures = iter(failures)
        self.acknowledged: list[str] = []
        self.failure_messages: list[str] = []

    async def acknowledge(self, message_id: str) -> None:
        self.acknowledged.append(message_id)

    async def handle_failure(self, message: QueuedPlanRun, error: str) -> QueueFailureResult:
        self.failure_messages.append(message.message_id)
        return next(self.failures)


class ExplodingService:
    def __init__(self):
        self.failed: list[str] = []

    async def execute_queued_run(self, initial: dict, session: dict) -> None:
        raise RuntimeError("boom")

    async def fail_queued_run(self, initial: dict, session: dict, *, error_code: str) -> None:
        self.failed.append(error_code)


@pytest.mark.asyncio
async def test_redis_stream_mode_enqueues_then_worker_executes(monkeypatch):
    monkeypatch.setattr(settings, "runtime_execution_mode", "redis_stream")
    queue = FakeQueue()
    service = PlanService(store=MemoryRuntimeStore(), task_queue=queue)

    started = await service.start_plan("徐汇区喝咖啡，预算100元")

    assert not service._tasks
    assert len(queue.items) == 1
    initial, session = queue.items[0]
    assert initial["run_id"] == started["run_id"]

    final = await service.execute_queued_run(initial, session)
    run = await service.get_run(started["run_id"])

    assert final is not None
    assert final["run_status"] == "completed"
    assert run["status"] == "completed"
    checkpoints = await service.list_run_checkpoints(started["run_id"])
    assert checkpoints
    assert checkpoints[-1]["phase"] == "route_present"


@pytest.mark.asyncio
async def test_failed_enqueue_can_retry_same_idempotency_key(monkeypatch):
    monkeypatch.setattr(settings, "runtime_execution_mode", "redis_stream")
    service = PlanService(store=MemoryRuntimeStore(), task_queue=FailingQueue())
    session_id = "00000000-0000-0000-0000-000000000081"

    with pytest.raises(QueueUnavailable):
        await service.start_plan("徐汇区喝咖啡", session_id=session_id, idempotency_key="retry-key")

    queue = FakeQueue()
    service._task_queue = queue
    retried = await service.start_plan("徐汇区喝咖啡", session_id=session_id, idempotency_key="retry-key")

    assert queue.items
    assert retried["run_id"] != ""


@pytest.mark.asyncio
async def test_async_api_returns_503_when_durable_queue_is_unavailable(client, monkeypatch):
    monkeypatch.setattr(settings, "runtime_execution_mode", "redis_stream")
    monkeypatch.setattr(app_plan_service, "_task_queue", FailingQueue())

    response = await client.post("/api/v1/routes/plan/runs", json={"query": "徐汇区喝咖啡"})

    assert response.status_code == 503
    assert response.json()["detail"] == "plan_queue_unavailable"


@pytest.mark.asyncio
async def test_worker_keeps_failed_message_pending_then_marks_exhausted_run_dead_lettered():
    service = ExplodingService()
    message = QueuedPlanRun(message_id="1-0", initial={"run_id": "run-1"}, session={"session_id": "session-1"})
    queue = WorkerQueue([QueueFailureResult(attempt=1, dead_lettered=False), QueueFailureResult(attempt=3, dead_lettered=True)])

    first = await process_message(service, queue, message)
    second = await process_message(service, queue, message)

    assert first == QueueFailureResult(attempt=1, dead_lettered=False)
    assert second == QueueFailureResult(attempt=3, dead_lettered=True)
    assert queue.acknowledged == []
    assert queue.failure_messages == ["1-0", "1-0"]
    assert service.failed == ["worker_retry_exhausted"]


@pytest.mark.asyncio
async def test_queued_run_failure_is_exposed_to_worker_retry(monkeypatch):
    service = PlanService(store=MemoryRuntimeStore())
    monkeypatch.setattr(service, "_execute_run", lambda initial, session: _failed_state())

    async def existing_run(*_args):
        return {"status": "running"}

    monkeypatch.setattr(service._store, "get_run", existing_run)

    with pytest.raises(QueuedRunFailed):
        await service.execute_queued_run(
            {"run_id": "00000000-0000-0000-0000-000000000091"},
            {"session_id": "00000000-0000-0000-0000-000000000092", "tenant_id": "default"},
        )


async def _failed_state() -> dict:
    return {"run_status": "failed", "error": "runtime_error"}
