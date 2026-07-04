"""规则引擎约束提取 — Step C1，供 constraint_extract 与 LLM 降级共用。"""

from __future__ import annotations

import re

from ..graph.state import GraphState
from ..models.constraints import Assumption, Constraints, IntentDomain

DISTRICTS = ["徐汇区", "静安区", "浦东新区", "黄浦区"]
DEFAULT_DISTRICT = "徐汇区"
DEFAULT_BUDGET = 150
DEFAULT_MINUTES = 180
DEFAULT_POI_COUNT = 3

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

_DINING_TRIGGER = ("吃", "美食", "餐", "饭", "逛吃", "料理", "聚餐", "宴请", "午餐", "晚餐")
_SIGHTSEEING_TRIGGER = ("逛", "玩", "游", "观光", "打卡", "展览", "博物馆", "公园", "景点", "逛逛")
_SHOPPING_TRIGGER = ("买", "购物", "逛街买", "商场")


def detect_preferred_cuisines(query: str) -> list[str] | None:
    hits: list[str] = []
    for term, keywords in CUISINE_KEYWORDS:
        if any(k in query for k in keywords):
            hits.append(term)
    return hits or None


def detect_district(query: str) -> str | None:
    for name in DISTRICTS:
        if name in query or name.replace("区", "") in query:
            return name
    return None


def detect_budget(query: str) -> int | None:
    match = re.search(r"(\d+)\s*(?:元|块)", query)
    if match:
        return int(match.group(1))
    if "200" in query:
        return 200
    return None


def detect_minutes(query: str) -> int | None:
    if "半天" in query:
        return 240
    match = re.search(r"(\d+)\s*(?:小时|个小时|h)", query, re.I)
    if match:
        return int(match.group(1)) * 60
    match = re.search(r"(\d+)\s*分钟", query)
    if match:
        return int(match.group(1))
    return None


def detect_return_by(query: str) -> str | None:
    match = re.search(r"(\d{1,2})\s*点\s*前?\s*回", query)
    if match:
        return f"{int(match.group(1)):02d}:00"
    return None


def detect_domains(query: str) -> list[IntentDomain]:
    """从 query 推断 POI 候选涉及的意图域（可多选，无 MIXED）。"""
    domains: list[IntentDomain] = []
    preferred = detect_preferred_cuisines(query)

    if preferred or any(k in query for k in _DINING_TRIGGER):
        domains.append(IntentDomain.DINING)
    if any(k in query for k in _SIGHTSEEING_TRIGGER):
        domains.append(IntentDomain.SIGHTSEEING)
    if any(k in query for k in _SHOPPING_TRIGGER):
        domains.append(IntentDomain.SHOPPING)

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


def _memory_assumption_value(state: GraphState, slot: str) -> str | None:
    memory = state.get("memory_context") or {}
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
    return any(k in query for k in (_DINING_TRIGGER + _SIGHTSEEING_TRIGGER + _SHOPPING_TRIGGER))


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

    district = detect_district(query)
    if not district:
        memory_district = _memory_assumption_value(state, "district")
        if memory_district in DISTRICTS:
            district = memory_district
            assumptions.append(_memory_assumption("district", district, f"沿用上一轮区域：{district}"))
        else:
            district = DEFAULT_DISTRICT
            assumptions.append(
                Assumption(
                    slot="district",
                    assumed_value=district,
                    source="scene_default",
                    message=f"未指定区域，默认推荐{district}",
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

    minutes = detect_minutes(query)
    return_by = detect_return_by(query)
    if minutes is None and return_by is None:
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

    domains = detect_domains(query)
    if not _query_has_domain_signal(query):
        domains = _memory_domains(state) or domains

    preferred_cuisines = detect_preferred_cuisines(query)
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

    constraints = Constraints(
        raw_query=query,
        domains=domains,
        district=district,
        time_budget_minutes=minutes,
        return_by=return_by,
        budget_per_person=budget,
        poi_count=DEFAULT_POI_COUNT,
        preferred_cuisines=preferred_cuisines,
        activity_tags=detect_activity_tags(query),
    )
    return constraints, assumptions
