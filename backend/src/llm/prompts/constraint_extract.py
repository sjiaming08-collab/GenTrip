"""constraint_extract Prompt 模板。"""

import json
from typing import Any

from ...services.constraint_rules import (
    DEFAULT_BUDGET,
    DEFAULT_DISTRICT,
    DEFAULT_MINUTES,
    DEFAULT_POI_COUNT,
    DISTRICTS,
)
from .system_contract import SYSTEM_CONTRACT

SYSTEM_PROMPT = SYSTEM_CONTRACT + """

你是 GenTrip 出行约束解析器，服务于上海本地路线规划。

规则：
1. 禁止向用户提问，禁止输出澄清问题。
2. 用户未明确给出的字段，优先参考 memory_context；仍缺失时使用合理默认值，并在 assumptions 中说明。
3. 当前用户 query 的显式表达优先级最高，不能被历史记忆覆盖。
4. 只输出一个 JSON 对象，字段见用户消息中的 schema。
5. district 只能是：徐汇区、静安区、浦东新区、黄浦区 之一；无法判断时可沿用 memory_context，仍无法判断用「徐汇区」并写入 assumptions。
6. domains 为用户 POI 候选涉及的意图域，可多选，取值：dining | sightseeing | shopping；至少 1 个。
7. domains 判定：含「吃/餐/美食/料理/菜系」→ 含 dining；「逛/玩/游/博物馆/公园/景点/打卡」→ 含 sightseeing；「买/购物/商场」→ 含 shopping。「逛吃/又逛又吃」→ ["dining","sightseeing"]，且 activity_tags 含「逛吃」。
8. start_at、return_by 格式为 HH:MM（24 小时制）；用户说「下午」时 start_at 为 14:00，明确「下午 3 点」时为 15:00。start_at 可与 return_by、time_budget_minutes 同时存在。
9. 用户明确排队容忍度时填写 queue_tolerance_minutes（不想排队为 0）；未提及则为 null。
10. budget_per_person、time_budget_minutes、poi_count 必须是正整数；缺失时在 assumptions 说明来源。
11. assumptions 每项包含 slot、assumed_value、message；仅记录推断/默认/沿用记忆值，用户已明确表述的不写入 assumptions。
12. 用户提到菜系或餐饮类型时，必须填写 preferred_cuisines（数组），填标准词不展开：
   「中餐/中国菜」→ ["中餐"]；「川菜/本帮/日料/西餐/咖啡」→ 对应词；只说「吃饭/美食」未指定菜系 → null。
"""


def _compact_memory(memory_context: dict[str, Any] | None) -> dict[str, Any]:
    memory = memory_context or {}
    return {
        "dialog_summary": memory.get("dialog_summary") or "",
        "route_intent": memory.get("route_intent"),
        "assumptions": memory.get("assumptions") or [],
        "recent_turns": [
            {
                "user_query": item.get("user_query"),
                "reply_type": item.get("reply_type"),
                "assumptions": item.get("assumptions") or [],
            }
            for item in (memory.get("recent_turns") or [])[-3:]
        ],
    }


def build_user_prompt(
    query: str,
    *,
    user_lat: float | None = None,
    user_lng: float | None = None,
    memory_context: dict[str, Any] | None = None,
) -> str:
    location = "未知"
    if user_lat is not None and user_lng is not None:
        location = f"lat={user_lat}, lng={user_lng}"

    memory_json = json.dumps(_compact_memory(memory_context), ensure_ascii=False, indent=2)

    return f"""解析以下用户出行需求，输出 JSON。

用户 query: {query}
用户位置: {location}
memory_context:
{memory_json}

优先级：
1. 当前 query 明确值
2. memory_context 中上一轮仍适用的约束和偏好
3. 场景默认值

支持的 district: {", ".join(DISTRICTS)}
默认值（缺失时使用）:
  district={DEFAULT_DISTRICT}
  budget_per_person={DEFAULT_BUDGET}
  time_budget_minutes={DEFAULT_MINUTES}
  poi_count={DEFAULT_POI_COUNT}

Duration examples: "five hours" and "玩五个小时" mean time_budget_minutes=300; "two and a half hours" and "两小时半" mean 150. When start_at and return_by are both explicit, also calculate their minute difference into time_budget_minutes.

JSON schema:
{{
  "domains": ["dining"|"sightseeing"|"shopping"|"leisure", ...],
  "district": "string|null",
  "time_budget_minutes": "integer|null",
  "start_at": "HH:MM|null",
  "return_by": "string|null",
  "queue_tolerance_minutes": "integer|null",
  "budget_per_person": "integer|null",
  "poi_count": "integer|null",
  "preferred_cuisines": ["string"] or null,
  "activity_tags": ["string"] or null,
  "assumptions": [
    {{"slot": "string", "assumed_value": "string", "message": "string", "source": "llm_inferred|session_memory|scene_default"}}
  ]
}}
"""
