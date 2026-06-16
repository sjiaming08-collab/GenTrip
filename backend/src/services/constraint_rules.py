"""规则引擎约束提取 — Step C1，供 constraint_extract 与 LLM 降级共用。"""

from __future__ import annotations

import re

from ..graph.state import GraphState
from ..models.constraints import Assumption, Constraints, TripPurpose

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


def detect_purpose(query: str) -> TripPurpose:
    if detect_preferred_cuisines(query):
        if any(k in query for k in ("逛", "玩")) and any(
            k in query for k in ("吃", "餐", "美食", "逛吃")
        ):
            return TripPurpose.MIXED
        return TripPurpose.DINING
    if any(k in query for k in ("博物馆", "美术馆", "展览")):
        return TripPurpose.SIGHTSEEING
    if any(k in query for k in ("吃", "美食", "餐", "饭")) and any(
        k in query for k in ("逛", "玩")
    ):
        return TripPurpose.MIXED
    if any(k in query for k in ("吃", "美食", "餐", "饭", "逛吃")):
        return TripPurpose.DINING
    if any(k in query for k in ("买", "购物")):
        return TripPurpose.SHOPPING
    if any(k in query for k in ("玩", "逛", "观光", "打卡")):
        return TripPurpose.SIGHTSEEING
    return TripPurpose.MIXED


def rule_based_extract(state: GraphState) -> tuple[Constraints, list[Assumption]]:
    """从 user_query 规则解析约束，缺失项补 assumptions（零 Clarify）。"""
    query = state["user_query"]
    assumptions: list[Assumption] = []

    district = detect_district(query)
    if not district:
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
        minutes = DEFAULT_MINUTES
        assumptions.append(
            Assumption(
                slot="time_budget_minutes",
                assumed_value=str(minutes),
                source="scene_default",
                message=f"未指定时长，默认 {minutes // 60} 小时行程",
            )
        )

    constraints = Constraints(
        raw_query=query,
        purpose=detect_purpose(query),
        district=district,
        time_budget_minutes=minutes,
        return_by=return_by,
        budget_per_person=budget,
        poi_count=DEFAULT_POI_COUNT,
        preferred_cuisines=detect_preferred_cuisines(query),
        activity_tags=["逛吃"] if "逛" in query or "玩" in query else None,
    )
    return constraints, assumptions
