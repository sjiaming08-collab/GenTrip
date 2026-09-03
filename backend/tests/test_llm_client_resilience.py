import asyncio

import httpx
import pytest

from src.config import settings
from src.llm.client import DeepSeekClient
from src.llm.exceptions import LLMError


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.request = httpx.Request("POST", "https://example.test/chat/completions")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "provider error",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request),
            )

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    responses: list[_FakeResponse] = []
    calls = 0
    init_calls = 0
    post_kwargs: list[dict] = []

    def __init__(self, **_kwargs) -> None:
        type(self).init_calls += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, *_args, **_kwargs) -> _FakeResponse:
        type(self).calls += 1
        type(self).post_kwargs.append(_kwargs)
        return type(self).responses.pop(0)


def _success_payload() -> dict:
    return {
        "choices": [{"message": {"content": '{"ok": true}'}}],
        "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
    }


@pytest.mark.asyncio
async def test_llm_client_retries_transient_status_and_reports_attempts(monkeypatch):
    monkeypatch.setattr("src.llm.client.httpx.AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(settings, "llm_max_retries", 2)
    monkeypatch.setattr(settings, "llm_retry_base_seconds", 0.0)
    _FakeAsyncClient.calls = 0
    _FakeAsyncClient.init_calls = 0
    _FakeAsyncClient.post_kwargs = []
    _FakeAsyncClient.responses = [_FakeResponse(429, {}), _FakeResponse(200, _success_payload())]

    data, meta = await DeepSeekClient(api_key="test").chat_json_with_meta("system", "user", operation="test")

    assert data == {"ok": True}
    assert meta["attempt_count"] == 2
    assert _FakeAsyncClient.calls == 2
    assert _FakeAsyncClient.init_calls == 1


@pytest.mark.asyncio
async def test_llm_client_applies_bounded_fast_operation_policy(monkeypatch):
    monkeypatch.setattr("src.llm.client.httpx.AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(settings, "llm_fast_model", "fast-model")
    monkeypatch.setattr(settings, "llm_disable_thinking", True)
    monkeypatch.setattr(settings, "llm_fast_timeout_sec", 7.0)
    _FakeAsyncClient.calls = 0
    _FakeAsyncClient.init_calls = 0
    _FakeAsyncClient.post_kwargs = []
    _FakeAsyncClient.responses = [_FakeResponse(200, _success_payload())]

    _, meta = await DeepSeekClient(api_key="test").chat_json_with_meta(
        "system", "user", operation="constraint_extract"
    )

    request = _FakeAsyncClient.post_kwargs[0]
    assert request["json"]["model"] == "fast-model"
    assert request["json"]["max_tokens"] == 512
    assert request["json"]["thinking"] == {"type": "disabled"}
    assert request["timeout"] == 7.0
    assert meta["model"] == "fast-model"
    assert meta["max_tokens"] == 512
    assert meta["thinking_enabled"] is False


@pytest.mark.asyncio
async def test_route_evaluate_has_hard_deadline_and_no_retry(monkeypatch):
    class SlowClient(_FakeAsyncClient):
        async def post(self, *_args, **_kwargs):
            type(self).calls += 1
            await asyncio.sleep(0.05)
            return _FakeResponse(200, _success_payload())

    monkeypatch.setattr("src.llm.client.httpx.AsyncClient", SlowClient)
    monkeypatch.setattr(settings, "llm_route_evaluate_timeout_sec", 0.01)
    monkeypatch.setattr(settings, "llm_max_retries", 2)
    SlowClient.calls = 0

    with pytest.raises(LLMError) as error:
        await DeepSeekClient(api_key="test").chat_json_with_meta(
            "system", "user", operation="route_evaluate"
        )

    assert error.value.meta["error_code"] == "timeout"
    assert error.value.meta["attempt_count"] == 1
    assert SlowClient.calls == 1


@pytest.mark.asyncio
async def test_llm_client_opens_circuit_after_repeated_failures(monkeypatch):
    monkeypatch.setattr("src.llm.client.httpx.AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(settings, "llm_max_retries", 0)
    monkeypatch.setattr(settings, "llm_circuit_failure_threshold", 2)
    monkeypatch.setattr(settings, "llm_circuit_open_seconds", 60.0)
    _FakeAsyncClient.calls = 0
    _FakeAsyncClient.responses = [_FakeResponse(500, {}), _FakeResponse(500, {})]
    client = DeepSeekClient(api_key="test")

    with pytest.raises(LLMError) as first:
        await client.chat_json_with_meta("system", "user", operation="test")
    with pytest.raises(LLMError) as second:
        await client.chat_json_with_meta("system", "user", operation="test")
    with pytest.raises(LLMError) as third:
        await client.chat_json_with_meta("system", "user", operation="test")

    assert first.value.meta["error_code"] == "http_5xx"
    assert second.value.meta["circuit_state"] == "open"
    assert third.value.meta["error_code"] == "circuit_open"
    assert _FakeAsyncClient.calls == 2
