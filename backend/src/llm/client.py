"""DeepSeek（OpenAI 兼容）HTTP 客户端。"""

from __future__ import annotations

import json
from typing import Any

import httpx

from ..config import settings
from .exceptions import LLMError, LLMParseError


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

    async def chat_json(self, system: str, user: str) -> dict[str, Any]:
        if not self.api_key:
            raise LLMError("LLM API key 未配置")

        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise LLMError(f"DeepSeek 请求失败: {exc}") from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMParseError(f"响应格式异常: {data}") from exc

        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMParseError(f"JSON 解析失败: {content}") from exc


_default_client: DeepSeekClient | None = None


def get_llm_client() -> DeepSeekClient:
    global _default_client
    if _default_client is None:
        _default_client = DeepSeekClient()
    return _default_client
