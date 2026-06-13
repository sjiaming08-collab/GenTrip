"""[1] constraint_extract — 规则提取 + 补全约束 + assumptions。"""

import re

from ...models.constraints import Assumption, Constraints, TripPurpose
from ..state import GraphState, phase_update


DISTRICTS = ["徐汇区", "静安区", "浦东新区", "黄浦区"]
DEFAULT_DISTRICT = "徐汇区"
DEFAULT_BUDGET = 150
DEFAULT_MINUTES = 180
DEFAULT_POI_COUNT = 3


def _detect_district(query: str) -> str | None:
    for name in DISTRICTS:
        if name in query or name.replace("区", "") in query:
            return name
    return None


def _detect_budget(query: str) -> int | None:
    match = re.search(r"(\d+)\s*(?:元|块)", query)
    if match:
        return int(match.group(1))
    if "200" in query:
        return 200
    return None


def _detect_minutes(query: str) -> int | None:
    if "半天" in query:
        return 240
    match = re.search(r"(\d+)\s*(?:小时|个小时|h)", query, re.I)
    if match:
        return int(match.group(1)) * 60
    match = re.search(r"(\d+)\s*分钟", query)
    if match:
        return int(match.group(1))
    return None


def _detect_return_by(query: str) -> str | None:
    match = re.search(r"(\d{1,2})\s*点\s*前?\s*回", query)
    if match:
        return f"{int(match.group(1)):02d}:00"
    return None


def _detect_purpose(query: str) -> TripPurpose:
    if any(k in query for k in ("吃", "美食", "餐", "逛吃")):
        return TripPurpose.MIXED
    if any(k in query for k in ("买", "购物")):
        return TripPurpose.SHOPPING
    if any(k in query for k in ("玩", "逛", "观光", "打卡")):
        return TripPurpose.SIGHTSEEING
    return TripPurpose.MIXED


async def constraint_extract(state: GraphState) -> dict:
    query = state["user_query"]
    assumptions: list[Assumption] = []

    district = _detect_district(query)
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

    budget = _detect_budget(query)
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

    minutes = _detect_minutes(query)
    return_by = _detect_return_by(query)
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
        purpose=_detect_purpose(query),
        district=district,
        time_budget_minutes=minutes,
        return_by=return_by,
        budget_per_person=budget,
        poi_count=DEFAULT_POI_COUNT,
        activity_tags=["逛吃"] if "逛" in query or "玩" in query else None,
    )

    return phase_update(
        "constraint_extract",
        constraints=constraints.model_dump(mode="json"),
        assumptions=[a.model_dump(mode="json") for a in assumptions],
        constraint_embedding=None,
        plan_path="cold",
    )
