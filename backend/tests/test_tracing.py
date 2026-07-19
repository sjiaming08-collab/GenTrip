import pytest
from opentelemetry import trace

from src.config import settings
from src.observability.tracing import configure_tracing
from src.runtime.store import MemoryRuntimeStore
from src.services.plan_service import PlanService


class FakeQueue:
    def __init__(self):
        self.items: list[tuple[dict, dict]] = []

    async def enqueue(self, initial: dict, session: dict) -> str:
        self.items.append((initial, session))
        return "1-0"


@pytest.mark.asyncio
async def test_redis_worker_keeps_enqueue_trace_context(monkeypatch):
    monkeypatch.setattr(settings, "runtime_execution_mode", "redis_stream")
    configure_tracing("gentrip-test")
    queue = FakeQueue()
    service = PlanService(store=MemoryRuntimeStore(), task_queue=queue)

    with trace.get_tracer("gentrip-test").start_as_current_span("request") as request_span:
        started = await service.start_plan("徐汇区喝咖啡", session_id="00000000-0000-0000-0000-000000000082")
        request_trace_id = f"{request_span.get_span_context().trace_id:032x}"

    initial, session = queue.items[0]
    assert "traceparent" in initial["_trace_context"]

    final = await service.execute_queued_run(initial, session)

    assert final is not None
    assert final["trace_id"] == request_trace_id
    assert final["trace_id"] != started["run_id"]


@pytest.mark.asyncio
async def test_sync_plan_response_contains_trace_id(client):
    response = await client.post("/api/v1/routes/plan", json={"query": "徐汇区喝咖啡"})

    assert response.status_code == 200
    trace_id = response.json()["meta"]["debug_trace_id"]
    assert len(trace_id) == 32
    assert all(char in "0123456789abcdef" for char in trace_id)
