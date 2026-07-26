import pytest

from src.config import settings
from src.llm.exceptions import LLMError


def _ops(calls):
    return [call["operation"] for call in calls]


@pytest.mark.asyncio
async def test_plan_api_includes_local_telemetry_when_llm_disabled(client):
    response = await client.post("/api/v1/routes/plan", json={"query": "????3??"})

    assert response.status_code == 200
    meta = response.json()["meta"]
    assert meta["debug_trace_id"] != response.json()["run_id"]
    assert len(meta["debug_trace_id"]) == 32
    assert [item["phase"] for item in meta["phase_log"]][:4] == [
        "turn_orchestrate",
        "constraint_extract",
        "planning_decision",
        "route_bundle_search",
    ]
    assert "route_present" in [item["phase"] for item in meta["phase_log"]]
    constraint_phase = next(item for item in meta["phase_log"] if item["phase"] == "constraint_extract")
    assert "duration=180min" in constraint_phase["summary"]
    assert "turn_orchestrate" in _ops(meta["llm_calls"])
    assert "constraint_extract" in _ops(meta["llm_calls"])
    assert "route_evaluate" in _ops(meta["llm_calls"])
    assert "route_present" in _ops(meta["llm_calls"])
    assert "session_summary" in _ops(meta["llm_calls"])
    assert {call["status"] for call in meta["llm_calls"]} == {"skipped"}
    assert meta["token_usage"] == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "call_count": 0,
    }
    assert {call["operation"] for call in meta["tool_calls"]} == {
        "poi_search",
        "travel_time",
        "route_bundle_search",
        "route_bundle_ingest",
    }


class UsageClient:
    async def chat_json_with_meta(self, system, user, *, operation="unknown", temperature=0.1):
        usage_by_operation = {
            "turn_classify": (40, 10),
            "route_evaluate": (100, 20),
            "route_present": (50, 10),
            "session_summary": (30, 5),
        }
        prompt_tokens, completion_tokens = usage_by_operation.get(operation, (0, 0))
        meta = {
            "operation": operation,
            "provider": "deepseek",
            "model": "test-model",
            "status": "success",
            "latency_ms": 1.5,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
        if operation == "turn_classify":
            return {"turn_mode": "plan", "primary_intent": "路线规划", "query_understanding": "test", "reason": "test", "replan_operation": None}, meta
        if operation == "route_evaluate":
            return {
                "scores": [
                    {
                        "plan_id": "r1",
                        "execution": 0.9,
                        "quality": 0.8,
                        "preference": 0.7,
                        "comment": "ok",
                    }
                ]
            }, meta
        if operation == "route_present":
            return {"title": "????????", "summary": "summary", "highlights": ["h1"]}, meta
        if operation == "session_summary":
            return {"dialog_summary": "summary"}, meta
        raise AssertionError(operation)


@pytest.mark.asyncio
async def test_plan_api_sums_mock_llm_usage(client, monkeypatch):
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(settings, "constraint_extract_mode", "rule_only")
    fake = UsageClient()
    monkeypatch.setattr("src.llm.route_evaluate.get_llm_client", lambda: fake)
    monkeypatch.setattr("src.llm.route_present.get_llm_client", lambda: fake)
    monkeypatch.setattr("src.llm.session_summary.get_llm_client", lambda: fake)
    monkeypatch.setattr("src.llm.turn_classify.get_llm_client", lambda: fake)

    response = await client.post("/api/v1/routes/plan", json={"query": "????3??"})

    assert response.status_code == 200
    meta = response.json()["meta"]
    assert meta["token_usage"] == {
        "prompt_tokens": 220,
        "completion_tokens": 45,
        "total_tokens": 265,
        "call_count": 4,
    }
    by_operation = {call["operation"]: call for call in meta["llm_calls"]}
    assert by_operation["constraint_extract"]["status"] == "skipped"
    assert by_operation["route_evaluate"]["model"] == "test-model"
    assert by_operation["session_summary"]["total_tokens"] == 35


class FailingClient:
    async def chat_json_with_meta(self, system, user, *, operation="unknown", temperature=0.1):
        raise LLMError("boom")


@pytest.mark.asyncio
async def test_llm_failure_is_recorded_and_route_falls_back(client, monkeypatch):
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(settings, "constraint_extract_mode", "rule_only")
    fake = FailingClient()
    monkeypatch.setattr("src.llm.route_evaluate.get_llm_client", lambda: fake)
    monkeypatch.setattr("src.llm.route_present.get_llm_client", lambda: fake)
    monkeypatch.setattr("src.llm.session_summary.get_llm_client", lambda: fake)
    monkeypatch.setattr("src.llm.turn_classify.get_llm_client", lambda: fake)

    response = await client.post("/api/v1/routes/plan", json={"query": "????3??"})

    assert response.status_code == 200
    body = response.json()
    assert body["run_status"] == "completed"
    by_operation = {call["operation"]: call for call in body["meta"]["llm_calls"]}
    assert by_operation["turn_orchestrate"]["status"] == "failed"
    assert by_operation["route_evaluate"]["status"] == "failed"
    assert by_operation["route_evaluate"]["fallback_used"] is True
    assert by_operation["route_present"]["status"] == "failed"
    assert body["meta"]["token_usage"]["call_count"] == 4
