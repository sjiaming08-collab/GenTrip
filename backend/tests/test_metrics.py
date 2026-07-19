import pytest

from src.observability.metrics import RuntimeMetrics


def test_runtime_metrics_render_prometheus_labels_and_tokens():
    metrics = RuntimeMetrics()
    metrics.record_run(
        {
            "plan_path": "hot",
            "llm_calls": [{"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}],
            "tool_calls": [{"operation": "route_bundle_search", "cache_hit": True}],
        },
        "completed",
        0.25,
    )

    rendered = metrics.render_prometheus()

    assert 'gentrip_plan_runs_total{status="completed",path="hot"} 1' in rendered
    assert 'gentrip_llm_tokens_total{token_type="total"} 20' in rendered
    assert 'gentrip_route_bundle_search_total{outcome="hit"} 1' in rendered


@pytest.mark.asyncio
async def test_metrics_endpoint_exposes_plan_runtime_metrics(client):
    response = await client.post("/api/v1/routes/plan", json={"query": "徐汇区喝咖啡，预算100元"})

    assert response.status_code == 200
    metrics = await client.get("/api/v1/metrics")
    assert metrics.status_code == 200
    assert metrics.headers["content-type"].startswith("text/plain")
    assert "gentrip_plan_runs_total" in metrics.text
    assert "gentrip_llm_tokens_total" in metrics.text
