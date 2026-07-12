import asyncio

import pytest

from src.runtime.store import MemoryRuntimeStore


async def _wait_for_terminal(client, run_id: str) -> dict:
    for _ in range(40):
        response = await client.get(f"/api/v1/routes/plan/runs/{run_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] in {"completed", "degraded", "failed", "cancelled"}:
            return body
        await asyncio.sleep(0.01)
    raise AssertionError("run did not reach a terminal state")


@pytest.mark.asyncio
async def test_async_run_persists_result_and_replays_events(client):
    started = await client.post("/api/v1/routes/plan/runs", json={"query": "徐汇逛吃"})

    assert started.status_code == 202
    run_id = started.json()["run_id"]
    terminal = await _wait_for_terminal(client, run_id)
    assert terminal["status"] in {"completed", "degraded"}
    assert terminal["result"]["run_id"] == run_id

    events = await client.get(f"/api/v1/routes/plan/runs/{run_id}/events")
    assert events.status_code == 200
    assert "event: phase" in events.text
    assert "event: complete" in events.text
    assert '"response"' in events.text


@pytest.mark.asyncio
async def test_memory_store_supersedes_active_run_for_same_session():
    store = MemoryRuntimeStore()
    await store.create_run("00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000010", {})
    await store.set_run_status("00000000-0000-0000-0000-000000000001", "running")

    cancelled = await store.create_run(
        "00000000-0000-0000-0000-000000000002",
        "00000000-0000-0000-0000-000000000010",
        {},
    )

    assert cancelled == ["00000000-0000-0000-0000-000000000001"]
    old_run = await store.get_run("00000000-0000-0000-0000-000000000001")
    assert old_run["status"] == "cancelled"
    assert old_run["error_code"] == "superseded"
