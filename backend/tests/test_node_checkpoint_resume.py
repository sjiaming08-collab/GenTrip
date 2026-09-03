import pytest

from src.config import settings
from src.graph.plan_graph import next_node_after_phase
from src.runtime.store import MemoryRuntimeStore
from src.services.plan_service import PlanService


def test_resume_target_uses_graph_routing_result():
    assert next_node_after_phase("turn_orchestrate", {"turn_mode": "plan"}) == "constraint_extract"
    assert next_node_after_phase("turn_orchestrate", {"turn_mode": "replan"}) == "replan_parse"
    assert next_node_after_phase("turn_orchestrate", {"turn_mode": "reject"}) == "reject_reply"
    assert next_node_after_phase("route_present", {}) == "resume_finalize"


def test_resume_target_after_geo_resolve_respects_blueprint_flag(monkeypatch):
    monkeypatch.setattr(settings, "planner_blueprint_enabled", True)
    monkeypatch.setattr(settings, "blueprint_feasibility_enabled", True)
    assert next_node_after_phase("geo_resolve", {}) == "activity_blueprint"
    assert next_node_after_phase("activity_blueprint", {}) == "blueprint_compile"
    assert next_node_after_phase("blueprint_compile", {}) == "poi_retrieve"

    monkeypatch.setattr(settings, "planner_blueprint_enabled", False)
    assert next_node_after_phase("geo_resolve", {}) == "poi_retrieve"


@pytest.mark.asyncio
async def test_worker_retry_resumes_after_last_completed_node():
    store = MemoryRuntimeStore()
    service = PlanService(store=store)
    initial, session = await service._prepare_run("黄浦区逛商场和吃饭，玩三个小时")
    await service.save_session(session)

    completed_turn = {
        **initial,
        "turn_mode": "plan",
        "route_intent": {
            "intent_type": "new_plan",
            "primary_intent": "路线规划",
            "secondary_intents": [],
            "query_understanding": "黄浦区三小时行程",
        },
        "current_phase": "turn_orchestrate",
        "phase_log": [
            {
                "phase": "turn_orchestrate",
                "status": "completed",
                "ts": "2026-08-16T00:00:00+00:00",
                "summary": "classified as plan",
            }
        ],
    }
    checkpoint = service._checkpoint_state(
        completed_turn,
        next_node="constraint_extract",
        session_version=session.version,
    )
    await store.save_run_checkpoint(
        session.tenant_id,
        initial["run_id"],
        "turn_orchestrate",
        1,
        checkpoint,
    )
    await store.set_run_status(initial["run_id"], "running")
    await store.set_run_status(initial["run_id"], "failed", error_code="runtime_error")

    final = await service.execute_queued_run(initial, session.model_dump(mode="json"))

    assert final is not None
    assert final["run_status"] in {"completed", "degraded"}
    phases = [item["phase"] for item in final["phase_log"]]
    assert phases.count("turn_orchestrate") == 1
    assert phases[1] == "constraint_extract"
    assert final["resumed_from_phase"] == "turn_orchestrate"
    assert final["resume_count"] == 1
    events = await store.get_events_after(session.tenant_id, initial["run_id"], 0)
    resumed = [event for event in events if event.get("data", {}).get("resumed")]
    assert resumed and resumed[-1]["data"]["resumed_from_phase"] == "turn_orchestrate"
    public_checkpoints = await service.list_run_checkpoints(initial["run_id"])
    assert public_checkpoints
    assert all("graph_state" not in item["state"] for item in public_checkpoints)


@pytest.mark.asyncio
async def test_stale_session_checkpoint_is_not_restored():
    store = MemoryRuntimeStore()
    service = PlanService(store=store)
    initial, session = await service._prepare_run("徐汇区喝咖啡")
    checkpoint = service._checkpoint_state(
        {**initial, "current_phase": "turn_orchestrate"},
        next_node="constraint_extract",
        session_version=session.version + 1,
    )
    await store.save_run_checkpoint(
        session.tenant_id,
        initial["run_id"],
        "turn_orchestrate",
        1,
        checkpoint,
    )

    restored = await service._restore_checkpoint_state(initial, session)

    assert restored is initial
    assert restored.get("resumed_from_phase") is None
