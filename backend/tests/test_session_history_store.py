import pytest

from src.models.session import SessionState, Turn
from src.runtime.store import MemoryRuntimeStore


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
