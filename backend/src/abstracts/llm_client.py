"""LLM 调用客户端抽象"""

from abc import ABC, abstractmethod
from typing import Any, TypeVar

T = TypeVar("T")


class BaseLLMClient(ABC):
    """
    LLM 调用抽象 — 统一 Chat Completion + 结构化输出的入口。

    实现类:
      - DeepSeekClient: langchain-openai + DeepSeek API
      - OllamaClient: 本地 Ollama 降级
    """

    @abstractmethod
    async def invoke(self, prompt: str, system_prompt: str = "") -> str:
        """自由文本调用 → 返回 LLM 文本响应"""
        ...

    @abstractmethod
    async def invoke_structured(
        self,
        prompt: str,
        output_schema: type[T],
        system_prompt: str = "",
    ) -> T:
        """结构化输出调用 → 返回 Pydantic model 实例 (with_structured_output)"""
        ...

    @abstractmethod
    async def invoke_with_tools(
        self,
        prompt: str,
        tools: list[dict[str, Any]],
        system_prompt: str = "",
    ) -> dict[str, Any]:
        """Tool-calling 调用 → 返回 tool 调用结果"""
        ...
