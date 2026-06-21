"""constraint_extract Prompt 模板。"""

from ...services.constraint_rules import (
    DEFAULT_BUDGET,
    DEFAULT_DISTRICT,
    DEFAULT_MINUTES,
    DEFAULT_POI_COUNT,
    DISTRICTS,
)

SYSTEM_PROMPT = """你是 GenTrip 出行约束解析器，服务于上海本地路线规划。

规则：
1. 禁止向用户提问，禁止输出澄清问题。
2. 用户未明确给出的字段，使用合理默认值，并在 assumptions 中说明。
3. 只输出一个 JSON 对象，字段见用户消息中的 schema。
4. district 只能是：徐汇区、静安区、浦东新区、黄浦区 之一；无法判断时用「徐汇区」并写入 assumptions。
5. domains 为用户 POI 候选涉及的意图域，可多选，取值：dining | sightseeing | shopping；至少 1 个。
6. domains 判定：含「吃/餐/美食/料理/菜系」→ 含 dining；「逛/玩/游/博物馆/公园/景点/打卡」→ 含 sightseeing；「买/购物/商场」→ 含 shopping。「逛吃/又逛又吃」→ ["dining","sightseeing"]，且 activity_tags 含「逛吃」。
7. return_by 格式为 HH:MM（24 小时制）；可与 time_budget_minutes 同时存在。
8. budget_per_person、time_budget_minutes、poi_count 必须是正整数；缺失时在 assumptions 说明默认值。
9. assumptions 每项包含 slot、assumed_value、message；仅记录推断/默认值，用户已明确表述的不写入 assumptions。
10. 用户提到菜系或餐饮类型时，必须填写 preferred_cuisines（数组），填标准词不展开：
   「中餐/中国菜」→ ["中餐"]；「川菜/本帮/日料/西餐/咖啡」→ 对应词；只说「吃饭/美食」未指定菜系 → null。
"""


def build_user_prompt(
    query: str,
    *,
    user_lat: float | None = None,
    user_lng: float | None = None,
) -> str:
    location = "未知"
    if user_lat is not None and user_lng is not None:
        location = f"lat={user_lat}, lng={user_lng}"

    return f"""解析以下用户出行需求，输出 JSON。

用户 query: {query}
用户位置: {location}

支持的 district: {", ".join(DISTRICTS)}
默认值（缺失时使用）:
  district={DEFAULT_DISTRICT}
  budget_per_person={DEFAULT_BUDGET}
  time_budget_minutes={DEFAULT_MINUTES}
  poi_count={DEFAULT_POI_COUNT}

JSON schema:
{{
  "domains": ["dining"|"sightseeing"|"shopping", ...],
  "district": "string|null",
  "time_budget_minutes": "integer|null",
  "return_by": "string|null",
  "budget_per_person": "integer|null",
  "poi_count": "integer|null",
  "preferred_cuisines": ["string"] or null,
  "activity_tags": ["string"] or null,
  "assumptions": [
    {{"slot": "string", "assumed_value": "string", "message": "string", "source": "llm_inferred"}}
  ]
}}
"""
