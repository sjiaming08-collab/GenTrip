"""Tool Router — LLM 可在单 Run 内自选工具（最多 3 次），结果去重缓存。"""

from __future__ import annotations

import json
from typing import Any


class ToolDef:
    """Registered tool definition."""
    name: str
    description: str
    parameters: dict  # JSON Schema

    def __init__(self, name: str, description: str, parameters: dict | None = None):
        self.name = name
        self.description = description
        self.parameters = parameters or {}


AVAILABLE_TOOLS: list[ToolDef] = [
    ToolDef(
        name="poi_detail",
        description="查询 POI 的详细信息（评分、人均、营业时间、UGC 摘要）",
        parameters={"type": "object", "properties": {"poi_id": {"type": "string"}}, "required": ["poi_id"]},
    ),
    ToolDef(
        name="business_hours",
        description="检查 POI 在指定日期是否营业",
        parameters={"type": "object", "properties": {"poi_id": {"type": "string"}, "date": {"type": "string"}}, "required": ["poi_id"]},
    ),
    ToolDef(
        name="distance",
        description="计算两个 POI 之间的直线距离（公里）",
        parameters={"type": "object", "properties": {"from_poi_id": {"type": "string"}, "to_poi_id": {"type": "string"}}, "required": ["from_poi_id", "to_poi_id"]},
    ),
]


class ToolLimitExceeded(Exception):
    """Raised when max tool calls per run is exceeded."""


class ToolRouter:
    """Per-run tool registry with dedup cache and call limit."""

    def __init__(self, max_calls_per_run: int = 3):
        self.max_calls = max_calls_per_run
        self._call_count = 0
        self._cache: dict[str, Any] = {}

    def _cache_key(self, tool_name: str, params: dict) -> str:
        return f"{tool_name}:{json.dumps(params, sort_keys=True, ensure_ascii=False)}"

    async def call(self, tool_name: str, params: dict) -> dict:
        """Execute a tool call, with dedup cache and call limit."""
        key = self._cache_key(tool_name, params)
        if key in self._cache:
            return self._cache[key]
        if self._call_count >= self.max_calls:
            raise ToolLimitExceeded(f"单 Run 最多 {self.max_calls} 次工具调用")
        result = await self._execute(tool_name, params)
        self._cache[key] = result
        self._call_count += 1
        return result

    async def _execute(self, tool_name: str, params: dict) -> dict:
        """Execute a specific tool. Currently returns stub data for POI fixtures."""
        if tool_name == "poi_detail":
            return {"poi_id": params.get("poi_id"), "rating": 4.5, "price_per_person": 120, "hours": "10:00-22:00"}
        elif tool_name == "business_hours":
            return {"poi_id": params.get("poi_id"), "is_open": True, "hours": "10:00-22:00"}
        elif tool_name == "distance":
            return {"distance_km": 2.5, "estimated_minutes": 15}
        return {"error": f"unknown tool: {tool_name}"}

    def to_openai_tools(self) -> list[dict]:
        """Export tool definitions in OpenAI function-calling format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in AVAILABLE_TOOLS
        ]

    def state(self) -> dict:
        return {"call_count": self._call_count, "cache_keys": list(self._cache.keys())}
