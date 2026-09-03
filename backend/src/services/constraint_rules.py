"""规则引擎约束提取 — Step C1，供 constraint_extract 与 LLM 降级共用。"""

from __future__ import annotations

import re

from ..graph.state import GraphState
from ..models.constraints import Assumption, Constraints, IntentDomain
from .geo_resolver import extract_location_mentions as extract_gazetteer_mentions

DISTRICTS = [
    "黄浦区", "徐汇区", "长宁区", "静安区", "普陀区", "虹口区", "杨浦区",
    "浦东新区", "闵行区", "宝山区", "嘉定区", "金山区", "松江区", "青浦区",
    "奉贤区", "崇明区",
]
DEFAULT_CITY = "上海"
# Kept for compatibility with older evaluation fixtures. Runtime geography no
# longer fills a missing district with this value.
DEFAULT_DISTRICT = "徐汇区"
DEFAULT_BUDGET = 150
DEFAULT_MINUTES = 180
DEFAULT_POI_COUNT = 3
MAX_DERIVED_POI_COUNT = 6

_HIGH_DENSITY_MARKERS = ("多安排", "尽量多", "多去几个", "丰富", "充实", "紧凑")
_LOW_DENSITY_MARKERS = ("轻松", "悠闲", "慢慢", "不赶", "别太赶")

CUISINE_KEYWORDS: list[tuple[str, list[str]]] = [
    ("中餐", ["中餐", "中国菜", "中式"]),
    ("本帮菜", ["本帮菜", "本帮", "上海菜"]),
    ("川菜", ["川菜", "四川菜"]),
    ("粤菜", ["粤菜", "广东菜"]),
    ("日料", ["日料", "日本料理", "寿司"]),
    ("西餐", ["西餐", "意大利餐", "法式"]),
    ("火锅", ["火锅"]),
    ("咖啡", ["咖啡", "咖啡馆"]),
    ("甜品", ["甜品", "甜点"]),
    ("小吃快餐", ["小吃", "快餐"]),
]

EXCLUDED_CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("火锅", ["火锅"]),
    ("博物馆", ["博物馆"]),
    ("公园", ["公园", "绿地"]),
    ("美术馆", ["美术馆"]),
    ("展览", ["展览"]),
    ("商场", ["商场", "百货"]),
]
_NEGATION_MARKERS = ("不想去", "不要去", "不去", "别去", "不吃", "不要", "不想", "跳过")

_DINING_TRIGGER = ("吃", "美食", "餐", "饭", "逛吃", "料理", "聚餐", "宴请", "午餐", "晚餐")
_SIGHTSEEING_TRIGGER = ("逛", "玩", "游", "观光", "打卡", "看展", "艺术展", "展览", "美术馆", "画廊", "艺术空间", "文化中心", "博物馆", "公园", "景点", "逛逛", "散步", "步道")
_SHOPPING_TRIGGER = ("买", "购物", "逛街", "商场", "百货", "书店", "买手店", "古着")
_LEISURE_TRIGGER = ("按摩", "足疗", "推拿", "SPA", "美容", "健身", "攀岩", "游泳", "羽毛球", "网球", "保龄球", "滑雪", "电玩", "游戏", "电竞", "桌游", "VR", "密室", "KTV", "演出", "剧场", "电影院", "Livehouse", "亲子")
_CHINESE_HOURS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def detect_preferred_cuisines(query: str) -> list[str] | None:
    hits: list[str] = []
    for term, keywords in CUISINE_KEYWORDS:
        if any(k in query for k in keywords):
            hits.append(term)
    return hits or None


def detect_excluded_categories(query: str) -> list[str]:
    """Extract explicit negative POI-category preferences from one turn."""
    excluded: list[str] = []
    clause_break = r"[，。；,;]|想|再|然后|还"
    for category, keywords in EXCLUDED_CATEGORY_KEYWORDS:
        matched = False
        for marker in _NEGATION_MARKERS:
            for keyword in keywords:
                pattern = rf"{re.escape(marker)}(?:(?!{clause_break}).){{0,12}}?{re.escape(keyword)}"
                if re.search(pattern, query):
                    matched = True
                    break
            if matched:
                break
        if matched:
            excluded.append(category)
    return excluded


def detect_district(query: str) -> str | None:
    for name in DISTRICTS:
        if name in query or name.replace("区", "") in query:
            return name
    return None


def detect_city(query: str) -> str | None:
    aliases = (
        "上海", "北京", "天津", "重庆", "杭州", "苏州", "南京", "广州", "深圳",
        "成都", "武汉", "西安", "长沙", "宁波", "无锡", "厦门", "青岛",
    )
    for name in aliases:
        if name in query:
            return f"{name}市" if not name.endswith("市") else name
    return None


def detect_location_mentions(query: str) -> list[str]:
    """Extract grounded place text without assigning an administrative area.

    The gazetteer handles known aliases. The syntax fallback only captures text
    directly attached to ``附近/周边`` so provider geocoding can resolve a named
    landmark such as 西湖 even when it is outside the local fixture catalog.
    """

    mentions = list(extract_gazetteer_mentions(query))
    candidates = [
        match.group(1)
        for match in re.finditer(
            r"(?:在|去|到|从)([\u4e00-\u9fffA-Za-z0-9·]{2,24}?)(?:附近|周边)",
            query,
        )
    ]
    if not candidates:
        candidates = [
            match.group(1)
            for match in re.finditer(
                r"(?:^|[，,。；;\s])([\u4e00-\u9fffA-Za-z0-9·]{2,20}?)(?:附近|周边)",
                query,
            )
        ]

    city = detect_city(query)
    city_prefix = city.removesuffix("市") if city else None
    for candidate in candidates:
        candidate = re.sub(r"^(?:今天|明天|后天|周末)", "", candidate).strip()
        if city_prefix and candidate.startswith(city_prefix):
            candidate = candidate[len(city_prefix):].strip()
        if not candidate or detect_city(candidate) or detect_district(candidate):
            continue
        if candidate not in mentions:
            mentions.append(candidate)
    return mentions


def detect_budget(query: str) -> int | None:
    match = re.search(r"(\d+)\s*(?:元|块)", query)
    if match:
        return int(match.group(1))
    # Also match "预算N" or "预算改成N" patterns without 元
    m2 = re.search(r"预算\D*(\d+)", query)
    if m2:
        return int(m2.group(1))
    return None


def _detect_minutes_legacy(query: str) -> int | None:
    queue_duration = re.search(r"\u6392\u961f.{0,12}?\d+\s*\u5206\u949f", query)
    if queue_duration:
        query = query.replace(queue_duration.group(0), "")
    if "半天" in query:
        return 240
    match = re.search(r"(\d+)\s*(?:小时|个小时|h)", query, re.I)
    if match:
        return int(match.group(1)) * 60
    match = re.search(r"(\d+)\s*分钟", query)
    if match:
        return int(match.group(1))
    return None


def derive_time_budget_minutes(start_at: str | None, return_by: str | None) -> int | None:
    """Derive available minutes when the user provides an explicit time window."""
    if not start_at or not return_by:
        return None
    try:
        start_hour, start_minute = (int(part) for part in start_at.split(":", 1))
        end_hour, end_minute = (int(part) for part in return_by.split(":", 1))
    except (TypeError, ValueError):
        return None
    start = start_hour * 60 + start_minute
    end = end_hour * 60 + end_minute
    return end - start if end > start else None


_DURATION_CHINESE_NUMBERS = {
    "\u4e00": 1, "\u4e24": 2, "\u4e8c": 2, "\u4e09": 3, "\u56db": 4,
    "\u4e94": 5, "\u516d": 6, "\u4e03": 7, "\u516b": 8, "\u4e5d": 9, "\u5341": 10,
}

_FULL_DAY_EXPRESSION_RE = re.compile(
    r"(?:一整天|整天|全天|一整日|整日|一日游|(?<!第)(?:(?:玩|逛|游|安排|待|呆)\s*)?一天)"
)


def detect_full_day_expression(query: str) -> str | None:
    """Return the exact full-day wording without assigning fixed minutes."""
    match = _FULL_DAY_EXPRESSION_RE.search(query)
    return match.group(0) if match else None


def _parse_duration_number(raw: str) -> float | None:
    try:
        return float(raw)
    except ValueError:
        pass
    if raw in _DURATION_CHINESE_NUMBERS:
        return float(_DURATION_CHINESE_NUMBERS[raw])
    if "\u5341" not in raw:
        return None
    before, _, after = raw.partition("\u5341")
    tens = _DURATION_CHINESE_NUMBERS.get(before, 1) if before else 1
    ones = _DURATION_CHINESE_NUMBERS.get(after, 0) if after else 0
    return float(tens * 10 + ones) if tens is not None and ones is not None else None


def detect_minutes(query: str) -> int | None:
    """Extract explicit trip duration while excluding queue-duration phrases."""
    queue_duration = re.search(r"\u6392\u961f.{0,12}?\d+\s*\u5206\u949f", query)
    if queue_duration:
        query = query.replace(queue_duration.group(0), "")
    if "\u534a\u5929" in query:
        return 240
    if detect_full_day_expression(query):
        return 480
    match = re.search(
        r"(\d+(?:\.\d+)?|[\u4e00\u4e8c\u4e24\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341]+)\s*(?:\u4e2a)?\s*(\u534a)?\s*(?:\u5c0f\u65f6|\u949f\u5934|h)\s*(\u534a)?",
        query,
        re.I,
    )
    if match:
        hours = _parse_duration_number(match.group(1))
        if hours is not None:
            return round(hours * 60) + (30 if match.group(2) or match.group(3) else 0)
    if re.search(r"\u534a\s*(?:\u4e2a)?\s*(?:\u5c0f\u65f6|\u949f\u5934)", query):
        return 30
    match = re.search(r"(\d+|[\u4e00\u4e8c\u4e24\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341]+)\s*\u5206\u949f", query)
    if match:
        minutes = _parse_duration_number(match.group(1))
        if minutes is not None:
            return round(minutes)
    return None


def detect_poi_count(query: str) -> int | None:
    """Extract an explicit requested stop/activity count, excluding party size."""
    match = re.search(
        r"(?:安排|游玩|逛|去|包含|包括)?\s*"
        r"(\d{1,2}|[一二两三四五六七八九十]+)\s*个?\s*"
        r"(?:活动|地点|景点|去处|项目|站)",
        query,
    )
    if not match:
        return None
    value = _parse_duration_number(match.group(1))
    if value is None or not value.is_integer():
        return None
    count = int(value)
    return count if 1 <= count <= 12 else None


def should_enforce_poi_count(query: str) -> bool:
    """Return whether stop count is part of the user's scheduling intent."""
    if detect_poi_count(query) is not None:
        return True
    schedule_minutes = detect_minutes(query)
    if schedule_minutes is None:
        schedule_minutes = derive_time_budget_minutes(
            detect_start_at(query),
            detect_return_by(query),
        )
    if schedule_minutes is not None and schedule_minutes >= 360:
        return True
    return any(marker in query for marker in _HIGH_DENSITY_MARKERS)


def derive_poi_count(
    query: str,
    time_budget_minutes: int | None,
    *,
    suggested_count: int | None = None,
) -> int:
    """Resolve an explicit or duration-aware route stop target."""
    explicit_count = detect_poi_count(query)
    if explicit_count is not None:
        return explicit_count

    suggested = max(
        1,
        min(int(suggested_count or DEFAULT_POI_COUNT), MAX_DERIVED_POI_COUNT),
    )
    has_explicit_schedule = detect_minutes(query) is not None or (
        detect_start_at(query) is not None and detect_return_by(query) is not None
    )
    if not has_explicit_schedule or not time_budget_minutes:
        if any(marker in query for marker in _HIGH_DENSITY_MARKERS):
            return min(MAX_DERIVED_POI_COUNT, max(suggested, DEFAULT_POI_COUNT + 1))
        return suggested

    minutes = max(1, int(time_budget_minutes))
    if minutes <= 120:
        target = 2
    elif minutes <= 240:
        target = 3
    elif minutes <= 360:
        target = 4
    elif minutes <= 540:
        target = 5
    else:
        target = MAX_DERIVED_POI_COUNT

    if any(marker in query for marker in _LOW_DENSITY_MARKERS):
        target = max(2, target - 1)
    elif any(marker in query for marker in _HIGH_DENSITY_MARKERS):
        target = min(MAX_DERIVED_POI_COUNT, target + 1)
    return target


def derive_minimum_poi_count(
    query: str,
    time_budget_minutes: int | None,
    *,
    target_count: int,
    domains: list[str] | None = None,
) -> int:
    """Return the shortest acceptable route without turning a target into a cliff."""
    target = max(1, min(int(target_count), MAX_DERIVED_POI_COUNT))
    if should_enforce_poi_count(query):
        return target
    if detect_minutes(query) is None and not (
        detect_start_at(query) and detect_return_by(query)
    ):
        return 1
    minutes = max(1, int(time_budget_minutes or 0))
    if minutes <= 120:
        minimum = 1
    elif minutes <= 180:
        minimum = 1 if set(domains or []) == {"dining"} else 2
    elif minutes <= 240:
        minimum = 2
    elif minutes <= 360:
        minimum = 3
    elif minutes <= 540:
        minimum = 4
    else:
        minimum = max(1, target - 1)
    return min(target, minimum)


def detect_return_by(query: str) -> str | None:
    match = re.search(r"(?:(上午|早上|中午|下午|午后|晚上|夜间)\s*)?(\d{1,2})\s*点\s*前?\s*回", query)
    if match:
        label = match.group(1)
        hour = int(match.group(2))
        if label in {"下午", "午后", "晚上", "夜间"} and 1 <= hour <= 11:
            hour += 12
        if label == "中午" and hour < 11:
            hour += 12
        if 0 <= hour <= 23:
            return f"{hour:02d}:00"
    return None


def detect_start_at(query: str) -> str | None:
    explicit = re.search(r"(?:(上午|早上|中午|下午|午后|晚上|夜间)\s*)?(?:从|在)?\s*(\d{1,2})\s*(?:点|:)(\d{2})?\s*(?:出发|开始|以后|之后)", query)
    if explicit:
        label = explicit.group(1)
        hour = int(explicit.group(2))
        minute = int(explicit.group(3) or 0)
        if label in {"下午", "午后", "晚上", "夜间"} and 1 <= hour <= 11:
            hour += 12
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"

    period = re.search(r"(上午|早上|中午|下午|午后|晚上|夜间)\s*(\d{1,2}|[一二两三四五六七八九十])?\s*点?", query)
    if not period:
        return None
    label, raw_hour = period.groups()
    defaults = {"上午": 9, "早上": 9, "中午": 12, "下午": 14, "午后": 14, "晚上": 18, "夜间": 19}
    hour = int(raw_hour) if raw_hour and raw_hour.isdigit() else _CHINESE_HOURS.get(raw_hour or "", defaults[label])
    if label in {"下午", "午后", "晚上", "夜间"} and 1 <= hour <= 11:
        hour += 12
    return f"{hour:02d}:00" if 0 <= hour <= 23 else None


def detect_queue_tolerance_minutes(query: str) -> int | None:
    if re.search(r"(?:不想|不要|不愿|别|不能)\s*排队", query):
        return 0
    for pattern in (
        r"排队.{0,8}?(?:不超过|最多|以内)\s*(\d+)\s*分(?:钟)?",
        r"(?:可以|可|能)?(?:接受|容忍)?\s*排队\s*(\d+)\s*分(?:钟)?",
    ):
        match = re.search(pattern, query)
        if match:
            return int(match.group(1))
    return 30 if "排队半小时" in query else None


def positive_domain_query(query: str) -> str:
    positive_query = query
    excluded = set(detect_excluded_categories(query))
    for category, keywords in EXCLUDED_CATEGORY_KEYWORDS:
        if category in excluded:
            for keyword in keywords:
                positive_query = positive_query.replace(keyword, "")
    return positive_query


def has_domain_signal(query: str) -> bool:
    positive_query = positive_domain_query(query)
    return any(k in positive_query for k in (_DINING_TRIGGER + _SIGHTSEEING_TRIGGER + _SHOPPING_TRIGGER + _LEISURE_TRIGGER))


def detect_domains(query: str) -> list[IntentDomain]:
    """从 query 推断 POI 候选涉及的意图域（可多选，无 MIXED）。"""
    positive_query = positive_domain_query(query)

    domains: list[IntentDomain] = []
    preferred = detect_preferred_cuisines(positive_query)

    if preferred or any(k in positive_query for k in _DINING_TRIGGER):
        domains.append(IntentDomain.DINING)
    shopping_signal = any(k in positive_query for k in _SHOPPING_TRIGGER)
    sightseeing_signal = any(k in positive_query for k in _SIGHTSEEING_TRIGGER)
    leisure_signal = any(k in positive_query for k in _LEISURE_TRIGGER)
    if shopping_signal or leisure_signal:
        sightseeing_signal = any(k in positive_query for k in _SIGHTSEEING_TRIGGER if k not in {"逛", "逛逛", "玩"})
    if sightseeing_signal:
        domains.append(IntentDomain.SIGHTSEEING)
    if shopping_signal:
        domains.append(IntentDomain.SHOPPING)
    if leisure_signal:
        domains.append(IntentDomain.LEISURE)

    if not domains:
        domains = [IntentDomain.SIGHTSEEING]
    return domains


def detect_activity_tags(query: str) -> list[str] | None:
    tags: list[str] = []
    if "逛吃" in query or ("逛" in query and any(k in query for k in ("吃", "餐", "美食", "饭"))):
        tags.append("逛吃")
    elif "逛" in query or "玩" in query:
        tags.append("逛")
    return tags or None


def detect_mobility_preferences(query: str) -> list[str]:
    preferences: list[str] = []
    if re.search(r"少走路|少步行|不想走|不要走|行动不便", query):
        preferences.append("少走路")
    if re.search(r"优先步行|喜欢走路|想散步", query):
        preferences.append("优先步行")
    if re.search(r"不骑车|不要骑行", query):
        preferences.append("不骑行")
    return preferences


def detect_scene_type(query: str) -> str | None:
    if re.search(r"情侣|约会|女朋友|男朋友|对象|爱人", query):
        return "couple"
    if re.search(r"亲子|孩子|小朋友|宝宝|一家人", query):
        return "family"
    if re.search(r"朋友|闺蜜|同学|聚会", query):
        return "friends"
    if re.search(r"一个人|独自|自己去", query):
        return "solo"
    return None


def _memory_assumption_value(state: GraphState, slot: str) -> str | None:
    memory = state.get("memory_context") or {}
    for fact in reversed(memory.get("memory_facts") or []):
        if fact.get("slot") != slot or fact.get("value") in (None, ""):
            continue
        value = fact["value"]
        return ",".join(str(item) for item in value) if isinstance(value, list) else str(value)
    current_constraints = memory.get("current_constraints") or {}
    if current_constraints.get(slot) is not None:
        value = current_constraints.get(slot)
        if isinstance(value, list):
            return ",".join(str(item) for item in value)
        return str(value)
    for item in memory.get("assumptions") or []:
        if item.get("slot") == slot and item.get("assumed_value"):
            return str(item["assumed_value"])
    for turn in reversed(memory.get("recent_turns") or []):
        for item in turn.get("assumptions") or []:
            if item.get("slot") == slot and item.get("assumed_value"):
                return str(item["assumed_value"])
    return None

def _memory_positive_int(state: GraphState, slot: str) -> int | None:
    raw = _memory_assumption_value(state, slot)
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _query_has_domain_signal(query: str) -> bool:
    return has_domain_signal(query)


def _memory_domains(state: GraphState) -> list[IntentDomain] | None:
    memory = state.get("memory_context") or {}
    current_constraints = memory.get("current_constraints") or {}
    raw_domains = current_constraints.get("domains")
    if raw_domains:
        domains: list[IntentDomain] = []
        for item in raw_domains:
            try:
                domains.append(IntentDomain(str(item)))
            except ValueError:
                continue
        if domains:
            return domains

    intent = memory.get("route_intent") or {}
    primary = str(intent.get("primary_intent") or "")
    if "逛吃" in primary:
        return [IntentDomain.DINING, IntentDomain.SIGHTSEEING]
    if "看展" in primary or "附近推荐" in primary or "路线规划" in primary:
        return [IntentDomain.SIGHTSEEING]

    raw = _memory_assumption_value(state, "domains")
    if not raw:
        return None
    domains = []
    for item in raw.split(","):
        try:
            domains.append(IntentDomain(item.strip()))
        except ValueError:
            continue
    return domains or None


def _memory_categories(state: GraphState, slot: str) -> list[str]:
    memory = state.get("memory_context") or {}
    current_constraints = memory.get("current_constraints") or {}
    raw = current_constraints.get(slot) or []
    return [str(item) for item in raw if str(item)] if isinstance(raw, list) else []

def _memory_assumption(slot: str, value: str, message: str) -> Assumption:
    return Assumption(
        slot=slot,
        assumed_value=value,
        source="session_memory",
        message=message,
    )


def rule_based_extract(state: GraphState) -> tuple[Constraints, list[Assumption]]:
    """从 user_query 规则解析约束，缺失项按 memory -> scene default 补全。"""
    query = state["user_query"]
    assumptions: list[Assumption] = []

    location_mentions = detect_location_mentions(query)
    district = detect_district(query)
    city = detect_city(query)
    if district in DISTRICTS and not city:
        city = "上海市"
    if not district and not city and not location_mentions:
        memory_district = _memory_assumption_value(state, "district")
        memory_city = _memory_assumption_value(state, "city")
        if memory_district:
            district = memory_district
            assumptions.append(_memory_assumption("district", district, f"沿用上一轮区域：{district}"))
        if memory_city:
            city = memory_city
            assumptions.append(_memory_assumption("city", city, f"沿用上一轮城市：{city}"))
        if not district and not city and (state.get("user_lat") is None or state.get("user_lng") is None):
            city = DEFAULT_CITY
            assumptions.append(
                Assumption(
                    slot="city",
                    assumed_value=city,
                    source="scene_default",
                    message=f"未指定地点，默认在{city}检索",
                )
            )

    budget = detect_budget(query)
    if budget is None:
        memory_budget = _memory_positive_int(state, "budget_per_person")
        if memory_budget is not None:
            budget = memory_budget
            assumptions.append(
                _memory_assumption("budget_per_person", str(budget), f"沿用上一轮预算：人均 {budget} 元")
            )
        else:
            budget = DEFAULT_BUDGET
            assumptions.append(
                Assumption(
                    slot="budget_per_person",
                    assumed_value=str(budget),
                    source="scene_default",
                    message=f"未指定预算，默认人均 {budget} 元",
                )
            )

    start_at = detect_start_at(query)
    return_by = detect_return_by(query)
    minutes = detect_minutes(query)
    if minutes is None:
        derived_minutes = derive_time_budget_minutes(start_at, return_by)
        if derived_minutes is not None:
            minutes = derived_minutes
            assumptions.append(
                Assumption(
                    slot="time_budget_minutes",
                    assumed_value=str(minutes),
                    source="derived_time_window",
                    message=f"根据 {start_at} 至 {return_by} 计算可用时长：{minutes} 分钟",
                    overridable=False,
                )
            )
    if minutes is None:
        memory_minutes = _memory_positive_int(state, "time_budget_minutes")
        if memory_minutes is not None:
            minutes = memory_minutes
            assumptions.append(
                _memory_assumption("time_budget_minutes", str(minutes), f"沿用上一轮时长：{minutes} 分钟")
            )
        else:
            minutes = DEFAULT_MINUTES
            assumptions.append(
                Assumption(
                    slot="time_budget_minutes",
                    assumed_value=str(minutes),
                    source="scene_default",
                    message=f"未指定时长，默认 {minutes // 60} 小时行程",
                )
            )

    if start_at is None:
        memory_start_at = _memory_assumption_value(state, "start_at")
        if memory_start_at:
            start_at = memory_start_at
            assumptions.append(_memory_assumption("start_at", start_at, f"沿用上一轮出发时间：{start_at}"))

    queue_tolerance_minutes = detect_queue_tolerance_minutes(query)
    if queue_tolerance_minutes is None:
        memory_queue_tolerance = _memory_assumption_value(state, "queue_tolerance_minutes")
        if memory_queue_tolerance is not None:
            try:
                queue_tolerance_minutes = max(0, int(memory_queue_tolerance))
            except ValueError:
                queue_tolerance_minutes = None
            if queue_tolerance_minutes is not None:
                assumptions.append(
                    _memory_assumption(
                        "queue_tolerance_minutes",
                        str(queue_tolerance_minutes),
                        f"沿用上一轮排队上限：{queue_tolerance_minutes} 分钟",
                    )
                )

    domains = detect_domains(query)
    if not _query_has_domain_signal(query):
        domains = _memory_domains(state) or domains

    preferred_cuisines = detect_preferred_cuisines(positive_domain_query(query))
    memory_cuisine = _memory_assumption_value(state, "preferred_cuisines")
    if preferred_cuisines is None and memory_cuisine:
        preferred_cuisines = [item.strip() for item in memory_cuisine.split(",") if item.strip()] or None
        if preferred_cuisines:
            assumptions.append(
                _memory_assumption(
                    "preferred_cuisines",
                    ",".join(preferred_cuisines),
                    f"沿用上一轮餐饮偏好：{'、'.join(preferred_cuisines)}",
                )
            )

    excluded_categories = detect_excluded_categories(query)
    if not excluded_categories:
        excluded_categories = _memory_categories(state, "excluded_categories")
        if excluded_categories:
            assumptions.append(
                _memory_assumption(
                    "excluded_categories",
                    ",".join(excluded_categories),
                    f"沿用上一轮避开项：{'、'.join(excluded_categories)}",
                )
            )

    explicit_anchor_count = detect_poi_count(query)
    poi_count = derive_poi_count(query, minutes, suggested_count=DEFAULT_POI_COUNT)
    if explicit_anchor_count is None and poi_count != DEFAULT_POI_COUNT:
        assumptions.append(
            Assumption(
                slot="poi_count",
                assumed_value=str(poi_count),
                source="duration_derived",
                message=f"按 {minutes} 分钟行程安排 {poi_count} 站",
            )
        )

    constraints = Constraints(
        raw_query=query,
        domains=domains,
        city=city,
        district=district,
        time_budget_minutes=minutes,
        start_at=start_at,
        return_by=return_by,
        queue_tolerance_minutes=queue_tolerance_minutes,
        budget_per_person=budget,
        poi_count=poi_count,
        anchor_count_explicit=explicit_anchor_count,
        poi_count_min=(poi_count if explicit_anchor_count else max(1, poi_count - 1)),
        poi_count_target=poi_count,
        poi_count_max=min(8, poi_count if explicit_anchor_count else poi_count + 2),
        preferred_cuisines=preferred_cuisines,
        activity_tags=detect_activity_tags(query),
        location_mentions=location_mentions,
        excluded_categories=excluded_categories,
        scene_type=detect_scene_type(query),
        mobility_preferences=detect_mobility_preferences(query),
        geo_relation=(
            "nearby"
            if location_mentions and any(word in query for word in ("附近", "周边"))
            else None
        ),
    )
    return constraints, assumptions
