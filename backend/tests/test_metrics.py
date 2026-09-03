import pytest

from src.observability.metrics import RuntimeMetrics
from src.runtime.store import MemoryRuntimeStore


def test_runtime_metrics_render_prometheus_labels_and_tokens():
    metrics = RuntimeMetrics()
    metrics.record_run(
        {
            "plan_path": "hot",
            "llm_calls": [{"operation": "route_present", "status": "success", "prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}],
            "tool_calls": [{"operation": "route_bundle_search", "status": "success", "cache_hit": True}],
            "phase_log": [{"phase": "route_present", "status": "completed"}],
        },
        "completed",
        0.25,
    )

    rendered = metrics.render_prometheus()

    assert 'gentrip_plan_runs_total{status="completed",path="hot"} 1' in rendered
    assert 'gentrip_llm_tokens_total{token_type="total"} 20' in rendered
    assert 'gentrip_route_bundle_search_total{outcome="hit"} 1' in rendered
    assert 'gentrip_llm_calls_total{operation="route_present",status="success",error_code="none"} 1' in rendered
    assert 'gentrip_tool_calls_total{operation="route_bundle_search",status="success"} 1' in rendered
    assert 'gentrip_plan_phases_total{phase="route_present",status="completed"} 1' in rendered


def test_runtime_metrics_render_persisted_worker_snapshot():
    metrics = RuntimeMetrics()
    rendered = metrics.render_prometheus({
        "runs": {("completed", "cold"): 2},
        "duration_seconds": {"completed": 1.5},
        "token_usage": {"prompt": 10, "completion": 5, "total": 15},
        "bundle_search": {"miss": 2},
        "llm_calls": {("constraint_extract", "success", "none"): 2},
        "tool_calls": {("poi_search", "success"): 2},
        "phases": {("poi_retrieve", "completed"): 2},
    })

    assert 'gentrip_llm_calls_total{operation="constraint_extract",status="success",error_code="none"} 2' in rendered
    assert 'gentrip_tool_calls_total{operation="poi_search",status="success"} 2' in rendered
    assert 'gentrip_plan_phases_total{phase="poi_retrieve",status="completed"} 2' in rendered


@pytest.mark.asyncio
async def test_memory_runtime_store_aggregates_worker_telemetry():
    store = MemoryRuntimeStore()
    await store.create_run("run-1", "tenant-1", "session-1", {})
    await store.set_run_status("run-1", "running")
    await store.set_run_status(
        "run-1",
        "completed",
        result={
            "plan_path": "cold",
            "llm_calls": [{"operation": "constraint_extract", "status": "success"}],
            "tool_calls": [{"operation": "route_bundle_search", "status": "success", "cache_hit": True}],
            "phase_log": [{"phase": "constraint_extract", "status": "completed"}],
        },
        token_usage={"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
    )

    snapshot = await store.aggregate_run_metrics()

    assert snapshot["llm_calls"] == {("constraint_extract", "success", "none"): 1}
    assert snapshot["tool_calls"] == {("route_bundle_search", "success"): 1}
    assert snapshot["phases"] == {("constraint_extract", "completed"): 1}
    assert snapshot["bundle_search"] == {"hit": 1}


@pytest.mark.asyncio
async def test_metrics_endpoint_exposes_plan_runtime_metrics(client):
    response = await client.post("/api/v1/routes/plan", json={"query": "徐汇区喝咖啡，预算100元"})

    assert response.status_code == 200
    metrics = await client.get("/api/v1/metrics")
    assert metrics.status_code == 200
    assert metrics.headers["content-type"].startswith("text/plain")
    assert "gentrip_plan_runs_total" in metrics.text
    assert "gentrip_llm_tokens_total" in metrics.text
