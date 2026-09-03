import pytest

from src.runtime.store import InvalidRunStatusTransition, MemoryRuntimeStore


@pytest.mark.asyncio
async def test_run_state_machine_accepts_normal_completion():
    store = MemoryRuntimeStore()
    await store.create_run("run-normal", "tenant", "session", {})

    await store.set_run_status("run-normal", "running")
    await store.set_run_status("run-normal", "completed", result={"ok": True})

    run = await store.get_run("tenant", "run-normal")
    assert run["status"] == "completed"
    assert run["result"] == {"ok": True}


@pytest.mark.asyncio
async def test_terminal_run_cannot_be_overwritten_by_stale_cancellation():
    store = MemoryRuntimeStore()
    await store.create_run("run-terminal", "tenant", "session", {})
    await store.set_run_status("run-terminal", "running")
    await store.set_run_status("run-terminal", "completed")

    with pytest.raises(InvalidRunStatusTransition, match="completed->cancelled"):
        await store.set_run_status("run-terminal", "cancelled")


@pytest.mark.asyncio
async def test_retry_clears_previous_terminal_fields():
    store = MemoryRuntimeStore()
    await store.create_run("run-retry", "tenant", "session", {})
    await store.set_run_status("run-retry", "running")
    await store.set_run_status(
        "run-retry",
        "failed",
        result={"error": "runtime_error"},
        token_usage={"total_tokens": 10},
        error_code="runtime_error",
    )

    await store.set_run_status("run-retry", "running")
    run = await store.get_run("tenant", "run-retry")

    assert run is not None
    assert run["status"] == "running"
    assert run["completed_at"] is None
    assert run["error_code"] is None
    assert run["result"] is None
    assert run["token_usage"] == {}


@pytest.mark.asyncio
async def test_failed_worker_delivery_can_retry_but_cancelled_run_cannot():
    store = MemoryRuntimeStore()
    await store.create_run("run-retry", "tenant", "session", {})
    await store.set_run_status("run-retry", "running")
    await store.set_run_status("run-retry", "failed", error_code="runtime_error")
    await store.set_run_status("run-retry", "running")

    await store.create_run("run-cancelled", "tenant", "other-session", {})
    await store.set_run_status("run-cancelled", "cancelled")
    with pytest.raises(InvalidRunStatusTransition, match="cancelled->running"):
        await store.set_run_status("run-cancelled", "running")
