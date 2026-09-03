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


class HeartbeatQueue(WorkerQueue):
    def __init__(self):
        super().__init__([])
        self.touched: list[tuple[str, str]] = []

    async def touch(self, consumer: str, message_id: str) -> bool:
        self.touched.append((consumer, message_id))
        return True


class SlowService:
    async def execute_queued_run(self, initial: dict, session: dict) -> None:
        import asyncio

        await asyncio.sleep(0.15)


class ExplodingService:
    def __init__(self):
        self.failed: list[str] = []

    async def execute_queued_run(self, initial: dict, session: dict) -> None:
        raise RuntimeError("boom")

    async def fail_queued_run(self, initial: dict, session: dict, *, error_code: str) -> None:
        self.failed.append(error_code)


class FailingAgent:
    def __init__(self):
        self.calls = 0

    async def astream(self, *_args, **_kwargs):
        self.calls += 1
        if False:
            yield {}
        raise RuntimeError("graph failed")


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
    assert initial["memory_context"]["session_version"] == session["version"]

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
async def test_worker_heartbeats_active_stream_delivery(monkeypatch):
    monkeypatch.setattr(settings, "runtime_queue_heartbeat_ms", 10)
    queue = HeartbeatQueue()
    message = QueuedPlanRun(message_id="heartbeat-1", initial={}, session={})

    await process_message(SlowService(), queue, message, consumer="worker-a")

    assert queue.touched
    assert set(queue.touched) == {("worker-a", "heartbeat-1")}
    assert queue.acknowledged == ["heartbeat-1"]


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


@pytest.mark.asyncio
async def test_terminal_queued_run_is_not_executed_again(monkeypatch):
    service = PlanService(store=MemoryRuntimeStore())
    executed = False

    async def should_not_execute(*_args):
        nonlocal executed
        executed = True

    async def completed_run(*_args):
        return {"status": "completed"}

    monkeypatch.setattr(service, "_execute_run", should_not_execute)
    monkeypatch.setattr(service._store, "get_run", completed_run)

    result = await service.execute_queued_run(
        {"run_id": "00000000-0000-0000-0000-000000000093"},
        {"session_id": "00000000-0000-0000-0000-000000000094", "tenant_id": "default"},
    )

    assert result is None
    assert executed is False


@pytest.mark.asyncio
async def test_retryable_graph_failure_is_executed_again(monkeypatch):
    service = PlanService(store=MemoryRuntimeStore())
    executed = 0

    async def execute_again(initial, session):
        nonlocal executed
        executed += 1
        return {"run_status": "completed"}

    async def retryable_run(*_args):
        return {"status": "failed", "error_code": "runtime_error"}

    monkeypatch.setattr(service, "_execute_run", execute_again)
    monkeypatch.setattr(service._store, "get_run", retryable_run)

    result = await service.execute_queued_run(
        {"run_id": "00000000-0000-0000-0000-000000000095"},
        {"session_id": "00000000-0000-0000-0000-000000000096", "tenant_id": "default"},
    )

    assert result == {"run_status": "completed"}
    assert executed == 1


@pytest.mark.asyncio
async def test_persisted_graph_failure_reexecutes_pending_message():
    service = PlanService(store=MemoryRuntimeStore())
    agent = FailingAgent()
    service._agent = agent
    initial, session = await service._prepare_run("徐汇区喝咖啡")
    message = QueuedPlanRun(
        message_id="2-0",
        initial=initial,
        session=session.model_dump(mode="json"),
    )
    queue = WorkerQueue([
        QueueFailureResult(attempt=1, dead_lettered=False),
        QueueFailureResult(attempt=2, dead_lettered=False),
    ])

    first = await process_message(service, queue, message)
    second = await process_message(service, queue, message)

    assert first == QueueFailureResult(attempt=1, dead_lettered=False)
    assert second == QueueFailureResult(attempt=2, dead_lettered=False)
    assert agent.calls == 2
    assert (await service.get_run(initial["run_id"]))["error_code"] == "runtime_error"


async def _failed_state() -> dict:
    return {"run_status": "failed", "error": "runtime_error"}
