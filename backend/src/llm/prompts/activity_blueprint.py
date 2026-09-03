"""Prompt for one bounded semantic activity-blueprint call."""

import json

from ...models.constraints import Constraints


SYSTEM_PROMPT = """你是 GenTrip 的活动构思器。输出两个互有差异的活动蓝图：balanced 与 experiential。
你只负责活动类型、氛围、先后顺序和可选体验；禁止输出真实 POI 名称、地址、坐标、距离、交通耗时、价格、营业状态或排队时间。
只生成 role=anchor 或 role=optional 的语义槽位。午餐、晚餐、休息由后端规则加入，不要生成。
必须保留用户明确要求的活动类型和顺序；optional 槽位 required=false。每个蓝图最多 6 个语义槽位。
categories 与 activity_tags 必须使用简短中文词，供地图 Provider 检索；只有 slot_id 使用英文。
只输出 JSON，不要解释。
"""


def build_user_prompt(
    constraints: Constraints,
    *,
    start_at: str,
    return_by: str,
    scene_type: str,
) -> str:
    payload = {
        "query": constraints.raw_query,
        "domains": [item.value for item in constraints.domains],
        "start_at": start_at,
        "return_by": return_by,
        "time_budget_minutes": constraints.time_budget_minutes,
        "anchor_count_explicit": constraints.anchor_count_explicit,
        "activity_tags": constraints.activity_tags or [],
        "preferred_cuisines": constraints.preferred_cuisines or [],
        "excluded_categories": constraints.excluded_categories,
        "sequence_preferences": constraints.sequence_preferences,
        "scene_type": scene_type,
        "pace": constraints.pace,
    }
    return f"""约束：{json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}

输出紧凑 JSON；不要重复输入中的场景和起止时间，不要输出默认值或 null：
{{"blueprints":[{{
  "style":"balanced|experiential",
  "slots":[{{
    "slot_id":"英文短 ID",
    "role":"anchor|optional",
    "domain":"dining|sightseeing|shopping|leisure",
    "categories":["通用活动类别，不是真实店名"],
    "activity_tags":["氛围或体验标签"],
    "time_window":{{"start":"HH:MM","end":"HH:MM"}},
    "duration_minutes":60,
    "spatial_policy":"near_anchor|near_previous"
  }}]
}}]}}
time_window 仅在活动确有时段要求时输出；每种 style 恰好一份。
"""
