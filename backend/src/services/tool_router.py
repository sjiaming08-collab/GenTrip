"""Tool Router — LLM 可在单 Run 内自选工具（最多 3 次），结果去重缓存。"""

from __future__ import annotations

import json
from typing import Any

from .poi_hours import is_open_during, opening_intervals, parse_hhmm, weekday_from_date
from .poi_retrieval import _online_pois, _poi_id, _poi_lat_lng, _poi_price, _poi_queue_wait_min, _poi_rating
from .travel_time import travel_time_service


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
        parameters={"type": "object", "properties": {"poi_id": {"type": "string"}, "date": {"type": "string", "description": "YYYY-MM-DD, optional"}, "at_time": {"type": "string", "description": "HH:MM, optional"}}, "required": ["poi_id"]},
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
        """Execute fixture-backed POI tools without exposing raw fixture payloads."""
        def find(poi_id: object) -> dict | None:
            normalized = str(poi_id or "").removeprefix("dp:")
            for poi in _online_pois():
                if normalized in {str(_poi_id(poi)), str(poi.get("poi_id") or "")}:
                    return poi
            return None

        if tool_name == "poi_detail":
            poi = find(params.get("poi_id"))
            if poi is None:
                return {"error": "poi_not_found", "poi_id": params.get("poi_id")}
            return {
                "poi_id": f"dp:{_poi_id(poi)}",
                "name": poi.get("name"),
                "rating": _poi_rating(poi),
                "price_per_person": _poi_price(poi),
                "queue_wait_min": _poi_queue_wait_min(poi),
                "opening_hours": poi.get("opening_hours") or [],
                "ugc_summary": poi.get("ugc_summary") or None,
                "tags": poi.get("tags") or [],
            }
        if tool_name == "business_hours":
            poi = find(params.get("poi_id"))
            if poi is None:
                return {"error": "poi_not_found", "poi_id": params.get("poi_id")}
            at_minute = parse_hhmm(params.get("at_time"))
            intervals = opening_intervals(poi.get("opening_hours"))
            return {
                "poi_id": f"dp:{_poi_id(poi)}",
                "known": bool(intervals),
                "is_open": is_open_during(poi.get("opening_hours"), at_minute, at_minute + 1, weekday=weekday_from_date(params.get("date"))) if at_minute is not None else None,
                "opening_hours": poi.get("opening_hours") or [],
            }
        if tool_name == "distance":
            origin = find(params.get("from_poi_id"))
            destination = find(params.get("to_poi_id"))
            if origin is None or destination is None:
                return {"error": "poi_not_found"}
            from_lat, from_lng = _poi_lat_lng(origin)
            to_lat, to_lng = _poi_lat_lng(destination)
            estimate = await travel_time_service.estimate(from_lat, from_lng, to_lat, to_lng)
            return {"distance_km": round(estimate.distance_m / 1000, 2), "estimated_minutes": estimate.duration_min, "source": estimate.source, "fallback_used": estimate.fallback_used}
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
