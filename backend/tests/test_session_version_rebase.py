import pytest

from src.models.session import SessionState, Turn
from src.runtime.events import RuntimeEventBus
from src.runtime.store import MemoryRuntimeStore, SessionVersionConflict
from src.services.plan_service import PlanService


def _route_state(turn_id: str) -> dict:
    return {
        "run_id": f"run-{turn_id}",
        "turn_id": turn_id,
        "user_query": "预算改成每人300元，其他安排保持不变",
        "turn_mode": "replan",
        "run_status": "running",
        "current_phase": "route_present",
        "route_results": [{
            "route": {
                "plan_id": "route-v2",
                "stops": [{"poi_id": "poi-1"}, {"poi_id": "poi-2"}],
                "legs": [{"from_poi_id": "poi-1", "to_poi_id": "poi-2"}],
            }
        }],
        "constraints": {"budget_per_person": 300},
        "assumptions": [],
        "presentation": {"summary": "预算已调整"},
        "diff_result": {"changes": [{"field": "budget_per_person"}]},
        "phase_log": [],
        "llm_calls": [],
    }


@pytest.mark.asyncio
async def test_route_save_rebases_a_concurrent_metadata_only_write(monkeypatch):
    monkeypatch.setattr("src.services.plan_service.settings.session_summary_mode", "async_llm")
    store = MemoryRuntimeStore()
    service = PlanService(store=store, event_bus=RuntimeEventBus())
    original = SessionState(session_id="rebase-session", title="original")
    original.add_turn(Turn(turn_id="turn-1", user_query="西湖玩一天", reply_type="route"))
    await store.save_session(original)

    planning_snapshot = await store.load_session("rebase-session")
    metadata_snapshot = await store.load_session("rebase-session")
    assert planning_snapshot is not None and metadata_snapshot is not None
    metadata_snapshot.dialog_summary = "background summary"
    metadata_snapshot.dialog_summary_turn_id = "turn-1"
    metadata_snapshot.title = "renamed while planning"
    metadata_snapshot.confirmed_stop_ids = ["poi-confirmed"]
    await store.save_session(metadata_snapshot)

    await service._save_session(planning_snapshot, _route_state("turn-2"))

    restored = await store.load_session("rebase-session")
    assert restored is not None
    assert restored.version == 3
    assert restored.turn_count == 2
    assert [turn.turn_id for turn in restored.recent_turns] == ["turn-1", "turn-2"]
    assert restored.title == "renamed while planning"
    assert restored.confirmed_stop_ids == ["poi-confirmed"]
    assert restored.current_constraints == {"budget_per_person": 300}
    assert restored.current_route["plan_id"] == "route-v2"
    assert restored.latest_response["diff_result"]["changes"]


@pytest.mark.asyncio
async def test_route_save_still_rejects_a_genuinely_newer_turn(monkeypatch):
    monkeypatch.setattr("src.services.plan_service.settings.session_summary_mode", "async_llm")
    store = MemoryRuntimeStore()
    service = PlanService(store=store, event_bus=RuntimeEventBus())
    original = SessionState(session_id="superseded-session")
    original.add_turn(Turn(turn_id="turn-1", user_query="西湖玩一天", reply_type="route"))
    await store.save_session(original)

    stale_planning_snapshot = await store.load_session("superseded-session")
    newer = await store.load_session("superseded-session")
    assert stale_planning_snapshot is not None and newer is not None
    newer.add_turn(Turn(turn_id="turn-newer", user_query="换一条路线", reply_type="route"))
    await store.save_session(newer)

    with pytest.raises(SessionVersionConflict):
        await service._save_session(stale_planning_snapshot, _route_state("turn-stale"))

    restored = await store.load_session("superseded-session")
    assert restored is not None
    assert [turn.turn_id for turn in restored.recent_turns] == ["turn-1", "turn-newer"]
