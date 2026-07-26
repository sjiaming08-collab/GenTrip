import pytest

from src.models.session import SessionState, Turn
from src.config import settings
from src.runtime.store import MemoryRuntimeStore, SessionVersionConflict, TenantRunCapacityExceeded


@pytest.mark.asyncio
async def test_store_keeps_full_turn_history_after_session_context_is_trimmed():
    store = MemoryRuntimeStore()
    session = SessionState(session_id="history-store-001", user_id="test-user")

    for index in range(6):
        session.add_turn(Turn(
            turn_id=f"00000000-0000-0000-0000-{index + 1:012d}",
            user_query=f"query-{index + 1}",
            reply_type="route",
            assistant_message=f"reply-{index + 1}",
        ))
        await store.save_session(session)

    restored = await store.load_session(session.session_id)
    full_history = await store.load_turns(session.session_id)

    assert restored is not None
    assert len(restored.recent_turns) == 5
    assert [turn.user_query for turn in full_history] == [f"query-{index}" for index in range(1, 7)]


@pytest.mark.asyncio
async def test_store_rejects_a_stale_session_write():
    store = MemoryRuntimeStore()
    original = SessionState(session_id="cas-store-001", title="first")
    await store.save_session(original)
    stale = await store.load_session("cas-store-001")
    current = await store.load_session("cas-store-001")
    assert stale is not None and current is not None

    current.title = "newer"
    await store.save_session(current)
    stale.title = "stale"

    with pytest.raises(SessionVersionConflict):
        await store.save_session(stale)
    assert (await store.load_session("cas-store-001")).title == "newer"


@pytest.mark.asyncio
async def test_run_checkpoints_are_scoped_and_replace_the_same_phase_index():
    store = MemoryRuntimeStore()
    run_id = "00000000-0000-0000-0000-000000000101"
    await store.create_run(run_id, "default", "checkpoint-session", {"query": "test"})

    await store.save_run_checkpoint("default", run_id, "constraint_extract", 1, {"current_phase": "constraint_extract"})
    await store.save_run_checkpoint("default", run_id, "constraint_extract", 1, {"current_phase": "updated"})

    checkpoints = await store.list_run_checkpoints("default", run_id)
    assert len(checkpoints) == 1
    assert checkpoints[0]["state"]["current_phase"] == "updated"
    assert await store.list_run_checkpoints("another-tenant", run_id) == []


@pytest.mark.asyncio
async def test_tenant_active_run_capacity_keeps_same_session_replacement_available(monkeypatch):
    monkeypatch.setattr(settings, "runtime_tenant_max_active_runs", 1)
    store = MemoryRuntimeStore()
    await store.create_run("00000000-0000-0000-0000-000000000111", "default", "session-a", {})

    with pytest.raises(TenantRunCapacityExceeded):
        await store.create_run("00000000-0000-0000-0000-000000000112", "default", "session-b", {})

    replaced = await store.create_run("00000000-0000-0000-0000-000000000113", "default", "session-a", {})
    assert replaced == ["00000000-0000-0000-0000-000000000111"]
