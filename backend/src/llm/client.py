"""DeepSeek（OpenAI 兼容）HTTP 客户端。"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx
from opentelemetry import trace
from opentelemetry.trace.status import Status, StatusCode

from ..config import settings
from .exceptions import LLMError, LLMParseError


@dataclass(frozen=True)
class _OperationPolicy:
    model: str
    max_tokens: int
    timeout_sec: float
    max_retries: int


_MAX_TOKENS = {
    "turn_classify": 256,
    "constraint_extract": 512,
    "activity_blueprint": 900,
    "route_evaluate": 512,
    "route_present": 256,
    "session_summary": 256,
}


class DeepSeekClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_sec: float | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.llm_api_key
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.model = model or settings.llm_model
        self.timeout_sec = timeout_sec or settings.llm_timeout_sec
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0
        self._http_client: httpx.AsyncClient | None = None

    def _operation_policy(self, operation: str) -> _OperationPolicy:
        is_evaluation = operation == "route_evaluate"
        model = self.model if is_evaluation else (settings.llm_fast_model or self.model)
        timeout_sec = (
            settings.llm_route_evaluate_timeout_sec
            if is_evaluation
            else settings.llm_fast_timeout_sec
        )
        # Every planning operation has a deterministic fallback. Do not retry
        # inside the user request and multiply its tail latency; standalone
        # callers using an unknown operation retain one transient retry.
        max_retries = 0 if operation in _MAX_TOKENS else min(settings.llm_max_retries, 1)
        return _OperationPolicy(
            model=model,
            max_tokens=_MAX_TOKENS.get(operation, 512),
            timeout_sec=min(timeout_sec, self.timeout_sec),
            max_retries=max_retries,
        )

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=self.timeout_sec,
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            )
        return self._http_client

    async def aclose(self) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def chat_json(self, system: str, user: str) -> dict[str, Any]:
        data, _meta = await self.chat_json_with_meta(system, user)
        return data

    async def chat_json_with_meta(
        self,
        system: str,
        user: str,
        *,
        operation: str = "unknown",
        temperature: float = 0.1,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if not self.api_key:
            raise LLMError("LLM API key 未配置")

        policy = self._operation_policy(operation)
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": policy.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "temperature": temperature,
            "max_tokens": policy.max_tokens,
        }
        if settings.llm_disable_thinking:
            payload["thinking"] = {"type": "disabled"}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        span = trace.get_tracer("gentrip.llm").start_span("gentrip.llm.chat")
        span.set_attribute("gen_ai.provider.name", "deepseek")
        span.set_attribute("gen_ai.request.model", policy.model)
        span.set_attribute("gentrip.llm.operation", operation)
        span.set_attribute("gen_ai.request.max_tokens", policy.max_tokens)
        started = time.perf_counter()
        if time.monotonic() < self._circuit_open_until:
            span.set_status(Status(StatusCode.ERROR, "circuit_open"))
            span.end()
            raise LLMError(
                "DeepSeek circuit is open",
                meta={"operation": operation, "provider": "deepseek", "model": policy.model,
                      "attempt_count": 0, "error_code": "circuit_open", "circuit_state": "open"},
            )

        raw_response: dict[str, Any] | None = None
        last_error: Exception | None = None
        last_error_code = "llm_error"
        attempt_count = 0
        client = self._get_http_client()
        for attempt in range(policy.max_retries + 1):
            attempt_count = attempt + 1
            try:
                async with asyncio.timeout(policy.timeout_sec):
                    response = await client.post(
                        url, headers=headers, json=payload, timeout=policy.timeout_sec
                    )
                if response.status_code == 429:
                    last_error_code = "http_429"
                elif response.status_code >= 500:
                    last_error_code = "http_5xx"
                elif response.status_code >= 400:
                    last_error_code = "http_4xx"
                response.raise_for_status()
                raw_response = response.json()
                break
            except (TimeoutError, httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                last_error_code = (
                    "timeout"
                    if isinstance(exc, (TimeoutError, httpx.TimeoutException))
                    else "network_error"
                )
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code != 429 and exc.response.status_code < 500:
                    break
            except (ValueError, TypeError) as exc:
                last_error = exc
                last_error_code = "invalid_json"
            if attempt < policy.max_retries:
                await asyncio.sleep(settings.llm_retry_base_seconds * (2 ** attempt))

        if raw_response is None:
            self._consecutive_failures += 1
            if self._consecutive_failures >= settings.llm_circuit_failure_threshold:
                self._circuit_open_until = time.monotonic() + settings.llm_circuit_open_seconds
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            if last_error is not None:
                span.record_exception(last_error)
            span.set_status(Status(StatusCode.ERROR, last_error_code))
            span.end()
            raise LLMError(
                f"DeepSeek request failed: {last_error_code}",
                meta={"operation": operation, "provider": "deepseek", "model": policy.model,
                      "latency_ms": latency_ms, "attempt_count": attempt_count,
                      "max_tokens": policy.max_tokens,
                      "error_code": last_error_code,
                      "circuit_state": "open" if self._circuit_open_until > time.monotonic() else "closed"},
            ) from last_error

        self._consecutive_failures = 0
        self._circuit_open_until = 0.0

        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        usage = raw_response.get("usage") or {}
        meta = {
            "operation": operation,
            "provider": "deepseek",
            "model": policy.model,
            "status": "success",
            "latency_ms": latency_ms,
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
            "attempt_count": attempt_count,
            "max_tokens": policy.max_tokens,
            "thinking_enabled": not settings.llm_disable_thinking,
            "circuit_state": "closed",
        }
        span.set_attribute("gen_ai.usage.input_tokens", meta["prompt_tokens"])
        span.set_attribute("gen_ai.usage.output_tokens", meta["completion_tokens"])
        span.set_attribute("gentrip.llm.latency_ms", latency_ms)

        try:
            content = raw_response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, "response_shape_error"))
            span.end()
            raise LLMParseError(
                "DeepSeek response shape is invalid",
                meta={**meta, "error_code": "response_shape_error"},
            ) from exc

        try:
            parsed = json.loads(content)
            span.end()
            return parsed, meta
        except json.JSONDecodeError as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, "json_parse_error"))
            span.end()
            raise LLMParseError(
                "DeepSeek response content is not valid JSON",
                meta={**meta, "error_code": "invalid_json"},
            ) from exc


_default_client: DeepSeekClient | None = None


def get_llm_client() -> DeepSeekClient:
    global _default_client
    if _default_client is None:
        _default_client = DeepSeekClient()
    return _default_client


async def close_llm_client() -> None:
    global _default_client
    if _default_client is not None:
        await _default_client.aclose()
        _default_client = None
