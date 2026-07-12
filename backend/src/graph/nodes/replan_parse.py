"""[Replan 1] replan_parse — 解析用户的修订意图（纯规则）。"""

from __future__ import annotations

import re

from ..state import GraphState, phase_update

_DELETE_KEYWORDS = ("去掉", "删除", "跳过", "不去", "不想去", "不喜欢", "不要", "别去", "算了")
_REPLACE_KEYWORDS = ("换成", "改成", "替换", "换一家", "换一个")
_ADD_KEYWORDS = ("加一家", "再加", "增加", "追加", "加一个", "加一")
_CHANGE_PREF_KEYWORDS = ("预算改", "时间改", "改预算", "改时间", "换到")

# Categories that can be targeted in any operation
ALL_TARGET_CATEGORIES = [
    # Dining
    "本帮菜", "本帮江浙菜", "川菜", "湘菜", "粤菜", "港式", "日料", "寿司", "烧鸟",
    "西餐", "牛排", "东南亚菜", "火锅", "串串", "砂锅", "煲仔",
    "面馆", "面条", "小吃", "快餐", "轻食", "健康餐", "云南菜", "米线",
    "烧烤", "烤肉", "海鲜", "蟹宴", "西北菜", "东北菜",
    # Cafe
    "咖啡", "茶馆", "茶室", "甜品", "烘焙", "冰淇淋", "酒吧", "清吧", "啤酒",
    # Sightseeing
    "公园", "绿地", "博物馆", "美术馆", "展览", "街区", "地标", "观景台",
    "滨江", "步道", "历史建筑", "故居", "教堂", "寺庙",
    # Shopping
    "商场", "百货", "买手店", "书店", "古着",
    # Leisure
    "剧场", "演出", "脱口秀", "电影院", "密室", "剧本杀",
]

# Patterns to detect "I don't want X" / "not interested in X"
_NEGATION_PATTERNS = [
    re.compile(r"(?:不去|不想去|不喜欢|不要|别去|算了|不想|不看)(.+?)(?:呢|吧|了|啦|哈|啊|呀)?$"),
    re.compile(r"对(.+?)(?:没兴趣|不感兴趣|无感)"),
]


def _parse_seq(query: str) -> int | None:
    m = re.search(r"第\s*([一二三四五六七八九十\d]+)", query)
    if not m:
        return None
    num = m.group(1)
    char_map = {"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9,"十":10}
    if num in char_map:
        return char_map[num]
    try:
        return int(num)
    except ValueError:
        return None


def _parse_target_category(query: str) -> str | None:
    """Detect any category (dining/sightseeing/shopping/leisure) mentioned in query."""
    for c in sorted(ALL_TARGET_CATEGORIES, key=len, reverse=True):
        if c in query:
            return c
    return None


def _parse_cuisine(query: str) -> str | None:
    """Detect dining-specific category."""
    dining = {"日料","咖啡","甜品","火锅","川菜","粤菜","本帮菜","西餐","中餐","小吃","快餐","烧烤","面馆"}
    for c in dining:
        if c in query:
            return c
    return _parse_target_category(query)


def _parse_district(query: str) -> str | None:
    districts = ["徐汇区","静安区","浦东新区","黄浦区"]
    for d in districts:
        if d in query or d.replace("区","") in query:
            return d
    return None


def _find_stop_by_category(stops: list[dict], category: str) -> int | None:
    """Find stop index whose category/name contains the target category."""
    for i, stop in enumerate(stops):
        cat = stop.get("category","")
        name = stop.get("poi_name","")
        if category in cat or category in name:
            return i
    return None


def _parse_negation_target(query: str) -> str | None:
    """Extract the target of a negation: '不去公园' -> '公园'."""
    for pat in _NEGATION_PATTERNS:
        m = pat.search(query)
        if m:
            target = m.group(1).strip()
            # Check if the extracted target matches a known category
            return _parse_target_category(target) or target
    return None


async def replan_parse(state: GraphState) -> dict:
    query = state["user_query"].strip()
    memory = state.get("memory_context") or {}
    current_route = state.get("session_current_route") or state.get("original_route") or {}
    stops = current_route.get("stops", [])

    # Restore constraints from memory
    prev_constraints = memory.get("current_constraints") or {}
    constraints = dict(prev_constraints)
    geo_scope = state.get("geo_scope") or {}
    if not geo_scope and constraints.get("district"):
        geo_scope = {
            "resolved_name": constraints["district"],
            "scope_type": "district",
            "district": constraints["district"],
            "confidence": 0.8, "source": "session_memory",
        }

    # A route with no remaining stops cannot be revised locally. Treat the
    # incoming utterance as a fresh plan while preserving prior constraints.
    if not stops:
        return phase_update(
            "replan_parse",
            summary="empty route reroute=plan",
            turn_mode="plan",
            run_mode="plan",
            constraints=constraints if constraints else None,
            geo_scope=geo_scope if geo_scope else None,
            original_route=current_route,
        )

    # ---- LLM operation takes priority (from turn_orchestrate) ----
    llm_op = state.get("replan_operation") or {}
    if llm_op and llm_op.get("type"):
        operation = llm_op
        if operation["type"] == "change_pref" and operation.get("overrides"):
            for k, v in (operation["overrides"] or {}).items():
                constraints[k] = v
    else:
        # ---- Keyword fallback ----
        operation = None

    if operation is None:
        # 1. change_pref
        if any(k in query for k in _CHANGE_PREF_KEYWORDS) and not _parse_seq(query):
            overrides = {}
            budget_m = re.search(r"(\d+)\s*(?:元|块)?", query)
            if budget_m:
                overrides["budget_per_person"] = int(budget_m.group(1))
                constraints["budget_per_person"] = int(budget_m.group(1))
            district = _parse_district(query)
            if district:
                overrides["district"] = district
                constraints["district"] = district
                geo_scope = {"resolved_name": district, "scope_type": "district", "district": district, "confidence":0.9, "source":"user_override"}
            operation = {"type": "change_pref", "overrides": overrides}
        # 2. Delete
        elif any(k in query for k in _DELETE_KEYWORDS):
            seq = _parse_seq(query)
            target_cat = _parse_negation_target(query) or _parse_target_category(query)
            if target_cat and stops:
                cat_idx = _find_stop_by_category(stops, target_cat)
                seq = (cat_idx + 1) if cat_idx is not None else (seq or 1)
            operation = {"type": "delete", "target_seq": seq or 1, "target_category": target_cat}
        # 3. Replace
        elif _parse_seq(query) or any(k in query for k in _REPLACE_KEYWORDS):
            seq = _parse_seq(query) or 1
            cuisine = _parse_cuisine(query)
            district = _parse_district(query)
            if not cuisine:
                neg_target = _parse_negation_target(query)
                if neg_target:
                    cat_idx = _find_stop_by_category(stops, neg_target)
                    seq = (cat_idx + 1) if cat_idx is not None else seq
            operation = {"type": "replace", "target_seq": seq, "new_cuisine": cuisine, "new_district": district}
        # 4. Add
        elif any(k in query for k in _ADD_KEYWORDS):
            seq = _parse_seq(query)
            cuisine = _parse_cuisine(query)
            operation = {"type": "add", "after_seq": seq or len(stops), "new_cuisine": cuisine}
        # 5. Fallback
        else:
            neg_target = _parse_negation_target(query)
            if neg_target and stops:
                cat_idx = _find_stop_by_category(stops, neg_target)
                operation = {"type": "delete", "target_seq": (cat_idx + 1) if cat_idx is not None else 1, "target_category": neg_target}
            else:
                cuisine = _parse_cuisine(query)
                operation = {"type": "replace", "target_seq": 1, "new_cuisine": cuisine}

    # change_pref → re-route to plan path
    if operation["type"] == "change_pref":
        return phase_update(
            "replan_parse",
            summary=f"op={operation['type']} overrides={operation.get('overrides')} reroute=plan",
            turn_mode="plan", run_mode="plan",
            constraints=constraints if constraints else None,
            geo_scope=geo_scope if geo_scope else None,
            replan_operation=operation, original_route=current_route,
        )

    return phase_update(
        "replan_parse",
        summary=f"op={operation['type']} seq={operation.get('target_seq') or operation.get('after_seq')} cuisine={operation.get('new_cuisine')} target_cat={operation.get('target_category')}",
        constraints=constraints if constraints else None,
        geo_scope=geo_scope if geo_scope else None,
        replan_operation=operation, original_route=current_route,
    )
