"""当前轮显式约束提取 Prompt。

这里刻意不注入 memory、系统默认值或派生规则。那些信息由确定性服务合并，
使 Prompt 保持稳定，也让每个最终约束都有唯一责任方。
"""

import json
from typing import Any


SYSTEM_PROMPT = """你是 GenTrip 当前轮出行语义提取器。
只分析用户本轮 query；不要使用历史记忆，不要补默认值，不要生成 assumptions，也不要提问。
只输出一个 JSON 对象。缺失字段直接省略，不要为缺失字段输出 null 或空数组。

要求：
- 仅提取用户明确表达或可由原文直接换算的约束；禁止猜地点、预算、活动数量或用户偏好。
- 地点按最具体表达提取；“西湖附近”写为 text="西湖", relation="nearby"。
- 否定只作用于被否定对象，并用 activities.modality="prohibited" 或 excluded_categories_explicit 表达。
- domain 只是活动的语义提示；泛化词“玩”本身不能证明 leisure。
- 时间统一为 HH:MM；明确小时数可换算为分钟。“全天/玩一天”必须写 kind="full_day"，不得换算为固定分钟。
- anchor_count_explicit 只表示用户明确要求的活动/地点数量；餐饮、休息不计入。
- 不得输出 POI 名称、坐标、路程、营业状态或任何路线方案。
- contract_version 必须为 3。每个非空显式字段都给出 query 里的最短原文证据；不得改写证据。
"""


def build_user_prompt(
    query: str,
    *,
    user_lat: float | None = None,
    user_lng: float | None = None,
    memory_context: dict[str, Any] | None = None,
) -> str:
    # 保留参数以兼容调用方；GeoResolve 和归一化服务会处理坐标与记忆。
    del user_lat, user_lng, memory_context
    input_json = json.dumps({"query": query}, ensure_ascii=False, separators=(",", ":"))
    return f"""输入：{input_json}

输出字段：
{{
  "contract_version": 3,
  "turn_mode": "plan|reject",
  "primary_intent": "string",
  "query_understanding": "string",
  "domains_explicit": ["dining|sightseeing|shopping|leisure"],
  "city_explicit": "string|null",
  "district_explicit": "string|null",
  "geo_mentions": [{{"text":"string","relation":"exact|nearby|within_area","evidence":"query原文"}}],
  "time_expression": {{
    "kind":"exact_duration|clock_window|daypart|full_day|none",
    "start_at":"HH:MM|null","return_by":"HH:MM|null","duration_minutes":"positive integer|null",
    "qualifier":"exact|around|maximum|minimum|null","evidence":"query原文|null"
  }},
  "activities": [{{
    "text":"string","domain_hint":"dining|sightseeing|shopping|leisure|null",
    "categories":["string"],"modality":"required|preferred|prohibited","evidence":"query原文"
  }}],
  "queue_tolerance_minutes_explicit": "non-negative integer|null",
  "budget_per_person_explicit": "positive integer|null",
  "anchor_count_explicit": "positive integer|null",
  "preferred_cuisines_explicit": ["string"]|null,
  "activity_tags_explicit": ["string"]|null,
  "excluded_categories_explicit": ["string"],
  "sequence_preferences_explicit": ["string"],
  "scene_type_explicit": "solo|couple|friends|family|null",
  "pace_explicit": "relaxed|balanced|packed|null",
  "mobility_preferences_explicit": ["string"],
  "evidence": {{"field_name": "query 原文片段"}}
}}

V3 中地点只写 geo_mentions，时间只写 time_expression；不要重复输出旧版地点或时间字段。
"""
