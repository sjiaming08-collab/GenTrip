"""[Replan 1] replan_parse — normalize LLM operations with a rule fallback."""

from __future__ import annotations

import re

from ..state import GraphState, phase_update

_DELETE_KEYWORDS = ("去掉", "删除", "跳过", "不去", "不想去", "不喜欢", "不要", "别去", "算了")
_REPLACE_KEYWORDS = ("换成", "改成", "替换", "换一家", "换一个")
_ADD_KEYWORDS = ("加一家", "再加", "增加", "追加", "加一个", "加一", "还想去吃", "还想吃", "也想吃", "还要吃")
_CHANGE_PREF_KEYWORDS = ("预算改", "时间改", "改预算", "改时间", "换到")
_NO_MEAL_PATTERN = re.compile(r"(?:不|别|无需|不要)(?:安排)?(?:吃饭|用餐|餐饮|午餐|晚餐)")

# Categories that can be targeted in any operation
ALL_TARGET_CATEGORIES = [
    # Dining
    "本帮菜", "本帮江浙菜", "川菜", "湘菜", "粤菜", "港式", "日料", "寿司", "烧鸟",
    "西餐", "牛排", "东南亚菜", "火锅", "串串", "砂锅", "煲仔",
    "正餐", "简餐", "午餐", "晚餐", "面馆", "面条", "小吃", "快餐", "轻食", "健康餐", "云南菜", "米线",
    "烧烤", "烤肉", "海鲜", "蟹宴", "西北菜", "东北菜",
    # Cafe
    "咖啡", "茶馆", "茶室", "甜品", "烘焙", "冰淇淋", "酒吧", "清吧", "啤酒",
    # Sightseeing
    "公园", "绿地", "博物馆", "美术馆", "展览", "街区", "地标", "观景台",
    "滨江", "步道", "历史建筑", "故居", "教堂", "寺庙",
    # Shopping
    "商场", "百货", "买手店", "书店", "古着",
    # Leisure
    "按摩足疗", "按摩", "足疗", "推拿", "SPA", "采耳",
    "美容美体", "美容", "美甲", "美发", "护肤",
    "体育运动", "健身", "攀岩", "游泳", "羽毛球", "网球", "保龄球", "滑雪",
    "电玩游戏", "电玩", "游戏", "电竞", "桌游", "VR",
    "演出娱乐", "剧场", "演出", "脱口秀", "电影院", "KTV", "Livehouse", "密室", "剧本杀",
    "亲子游乐", "亲子乐园", "儿童乐园", "乐高",
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
    if "正餐" in query:
        return "正餐"
    if "简餐" in query:
        return "简餐"
    if any(term in query for term in ("美食", "吃东西", "吃点东西", "吃饭")):
        return "美食"
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


def _find_stop_by_slot(stops: list[dict], *, slot_id: str | None = None, role: str | None = None) -> int | None:
    for index, stop in enumerate(stops):
        if slot_id and stop.get("slot_id") == slot_id:
            return index
        if role and stop.get("slot_role") == role:
            return index
    return None


def _meal_period(query: str) -> str | None:
    if any(term in query for term in ("早餐", "早饭", "早上")):
        return "breakfast"
    if any(term in query for term in ("午餐", "午饭", "中午")):
        return "lunch"
    if any(term in query for term in ("晚餐", "晚饭", "晚上", "夜宵")):
        return "dinner"
    return None


def _find_meal_stop(stops: list[dict], period: str | None = None) -> int | None:
    meal_indices = [index for index, stop in enumerate(stops) if stop.get("slot_role") == "meal"]
    if not meal_indices:
        return None
    if period:
        for index in meal_indices:
            stop = stops[index]
            slot_id = str(stop.get("slot_id") or "").lower()
            if period in slot_id:
                return index
        target_hour = {"breakfast": 8, "lunch": 12, "dinner": 18}.get(period)
        if target_hour is not None:
            def distance(index: int) -> int:
                raw = str(stops[index].get("arrival_time") or "")
                try:
                    return abs(int(raw.split(":", 1)[0]) - target_hour)
                except (TypeError, ValueError):
                    return 24
            return min(meal_indices, key=distance)
    return meal_indices[0]


def _is_scoped_meal_adjustment(query: str) -> bool:
    return bool(_meal_period(query)) or any(
        term in query for term in ("正餐", "简餐", "吃饭", "用餐", "餐厅", "饭店")
    )


def _parse_negation_target(query: str) -> str | None:
    """Extract the target of a negation: '不去公园' -> '公园'."""
    for pat in _NEGATION_PATTERNS:
        m = pat.search(query)
        if m:
            target = m.group(1).strip()
            # Check if the extracted target matches a known category
            return _parse_target_category(target) or target
    return None


def _updated_turn_plan(state: GraphState, operations: list[dict], *, mode: str = "replan") -> dict:
    plan = dict(state.get("turn_plan") or {})
    affected = sorted({
        int(item["target_seq"])
        for item in operations
        if isinstance(item.get("target_seq"), int) and int(item["target_seq"]) > 0
    })
    plan.update({
        "turn_id": state.get("turn_id"),
        "mode": mode,
        "turn_relation": state.get("turn_relation") or plan.get("turn_relation"),
        "recompute_scope": state.get("recompute_scope") or plan.get("recompute_scope"),
        "operations": operations,
        "affected_stop_seqs": affected,
        "preserve_unmentioned_stops": mode == "replan",
        "source": plan.get("source") or (
            "llm" if any(item.get("source") == "llm" for item in operations) else "rule_fallback"
        ),
    })
    return plan


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
            turn_plan=_updated_turn_plan(state, [], mode="plan"),
            constraints=constraints if constraints else None,
            geo_scope=geo_scope if geo_scope else None,
            original_route=current_route,
        )

    if any(marker in query for marker in ("重新规划", "重新为我规划", "重做路线", "重新安排")):
        return phase_update(
            "replan_parse",
            summary="explicit full replan reroute=global_rebuild",
            turn_mode="replan",
            run_mode="replan",
            turn_relation="modify_current",
            recompute_scope="global_rebuild",
            constraints=constraints if constraints else None,
            geo_scope=geo_scope if geo_scope else None,
            replan_operation=None,
            replan_operations=[],
            turn_plan=_updated_turn_plan(state, []),
            original_route=current_route,
        )

    # ---- LLM operation takes priority (from turn_orchestrate) ----
    llm_ops = (state.get("turn_plan") or {}).get("operations") or state.get("replan_operations") or []
    if not llm_ops and state.get("replan_operation"):
        llm_ops = [state["replan_operation"]]
    if llm_ops and llm_ops[0].get("type"):
        operations = [dict(item) for item in llm_ops]
        operation = operations[0]
        for item in operations:
            if item.get("type") == "change_pref" and item.get("overrides"):
                constraints.update(item.get("overrides") or {})
    else:
        # ---- Keyword fallback ----
        operation = None

    # Slot-aware policy edit: remove only inferred meal slots and preserve all
    # confirmed anchors. Multiple meal slots become multiple local operations.
    if operation is None and _NO_MEAL_PATTERN.search(query):
        meal_indices = [
            index
            for index, stop in enumerate(stops)
            if stop.get("slot_role") == "meal"
            and stop.get("slot_source") in {"policy", "inferred"}
        ]
        if meal_indices:
            operations = [
                {
                    "type": "delete",
                    "target_seq": index + 1,
                    "target_slot_id": stops[index].get("slot_id"),
                    "target_category": None,
                    "confidence": 1.0,
                    "source": "rule_fallback",
                }
                for index in meal_indices
            ]
            operation = operations[0]

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
                if cat_idx is not None:
                    seq = cat_idx + 1
                elif seq is not None:
                    # "第1站" is an ordinal reference, not a category to persist
                    # as an exclusion constraint.
                    target_cat = None
            operation = {"type": "delete", "target_seq": seq or 1, "target_category": target_cat}
        # 3. Add. This must precede the ordinal replace fallback because
        # "在第1站后再加" contains a sequence but is still an insertion.
        elif any(k in query for k in _ADD_KEYWORDS):
            seq = _parse_seq(query)
            cuisine = _parse_cuisine(query)
            operation = {"type": "add", "after_seq": seq or len(stops), "new_cuisine": cuisine}
        # 4. Scoped meal constraint. It is a contextual replacement even when
        # the user omits an edit verb, e.g. "中午想吃正餐".
        elif _is_scoped_meal_adjustment(query) and _find_meal_stop(stops, _meal_period(query)) is not None:
            meal_index = _find_meal_stop(stops, _meal_period(query))
            assert meal_index is not None
            operation = {
                "type": "replace",
                "target_seq": meal_index + 1,
                "target_slot_id": stops[meal_index].get("slot_id"),
                "new_cuisine": _parse_cuisine(query) or "美食",
            }
        # 5. Replace
        elif _parse_seq(query) or any(k in query for k in _REPLACE_KEYWORDS):
            seq = _parse_seq(query) or 1
            cuisine = _parse_cuisine(query)
            district = _parse_district(query)
            target_slot_id = None
            if any(term in query for term in ("换一家餐厅", "换个餐厅", "换一家饭店", "换个吃饭")):
                meal_index = _find_stop_by_slot(stops, role="meal")
                if meal_index is not None:
                    seq = meal_index + 1
                    target_slot_id = stops[meal_index].get("slot_id")
                cuisine = cuisine or "美食"
            if not cuisine:
                neg_target = _parse_negation_target(query)
                if neg_target:
                    cat_idx = _find_stop_by_category(stops, neg_target)
                    seq = (cat_idx + 1) if cat_idx is not None else seq
            operation = {"type": "replace", "target_seq": seq, "target_slot_id": target_slot_id, "new_cuisine": cuisine, "new_district": district}
        # 6. Fallback
        else:
            neg_target = _parse_negation_target(query)
            if neg_target and stops:
                cat_idx = _find_stop_by_category(stops, neg_target)
                operation = {"type": "delete", "target_seq": (cat_idx + 1) if cat_idx is not None else 1, "target_category": neg_target}
            else:
                cuisine = _parse_cuisine(query)
                operation = {"type": "replace", "target_seq": 1, "new_cuisine": cuisine}

        operation["confidence"] = 1.0
        operation["source"] = "rule_fallback"
        operations = [operation]

    # A single utterance may remove one category while requesting another,
    # e.g. "不想去美术馆，想吃日料". The local replan graph already has a
    # replacement path with retrieval, so normalize this compound intent to a
    # replacement and retain the removed category as a future exclusion.
    normalized_operations: list[dict] = []
    for operation in operations:
        if operation.get("type") == "delete":
            target_category = operation.get("target_category") or _parse_negation_target(query)
            requested_cuisine = (
                _parse_cuisine(query)
                if len(operations) == 1 and not operation.get("target_slot_id")
                else None
            )
            if requested_cuisine and requested_cuisine != target_category:
                target_seq = operation.get("target_seq")
                if target_category:
                    target_index = _find_stop_by_category(stops, target_category)
                    if target_index is not None:
                        target_seq = target_index + 1
                operation = {
                    **operation,
                    "type": "replace",
                    "target_seq": target_seq or 1,
                    "target_category": target_category,
                    "new_cuisine": requested_cuisine,
                    "exclude_category": target_category,
                }
            elif target_category and not operation.get("target_seq"):
                target_index = _find_stop_by_category(stops, target_category)
                if target_index is not None:
                    operation = {**operation, "target_seq": target_index + 1}
        normalized_operations.append(operation)
    operations = normalized_operations
    # Resolve LLM-produced dining edits to the semantic meal slot as well. The
    # model may understand the delta but omit the route's opaque slot_id.
    if _is_scoped_meal_adjustment(query):
        meal_index = _find_meal_stop(stops, _meal_period(query))
        if meal_index is not None:
            for item in operations:
                if item.get("type") == "replace" and not item.get("target_slot_id"):
                    item["target_seq"] = meal_index + 1
                    item["target_slot_id"] = stops[meal_index].get("slot_id")
                    item["new_cuisine"] = item.get("new_cuisine") or _parse_cuisine(query) or "美食"
    for item in operations:
        target_slot_id = item.get("target_slot_id")
        if target_slot_id:
            slot_index = _find_stop_by_slot(stops, slot_id=str(target_slot_id))
            if slot_index is not None:
                item["target_seq"] = slot_index + 1
    operation = operations[0]

    # Preference changes need broad recomputation, but remain revisions of the
    # same conversational goal so lineage and diff rendering are preserved.
    if any(item.get("type") == "change_pref" for item in operations):
        return phase_update(
            "replan_parse",
            summary=f"ops={len(operations)} reroute={state.get('recompute_scope') or 'global_rebuild'}",
            turn_mode="replan", run_mode="replan",
            turn_relation="modify_current",
            recompute_scope=state.get("recompute_scope") or "global_rebuild",
            constraints=constraints if constraints else None,
            geo_scope=geo_scope if geo_scope else None,
            replan_operation=operation if len(operations) == 1 else None,
            replan_operations=operations,
            turn_plan=_updated_turn_plan(state, operations),
            original_route=current_route,
        )

    excluded = list(constraints.get("excluded_categories") or [])
    for item in operations:
        excluded_category = item.get("exclude_category")
        if item.get("type") == "delete":
            excluded_category = excluded_category or item.get("target_category")
        if excluded_category and str(excluded_category) not in excluded:
            excluded.append(str(excluded_category))
    if excluded:
        constraints["excluded_categories"] = excluded

    return phase_update(
        "replan_parse",
        summary=f"op={operation['type']} seq={operation.get('target_seq') or operation.get('after_seq')} cuisine={operation.get('new_cuisine')} target_cat={operation.get('target_category')} source={operation.get('source', 'unknown')}",
        constraints=constraints if constraints else None,
        geo_scope=geo_scope if geo_scope else None,
        replan_operation=operation if len(operations) == 1 else None,
        replan_operations=operations,
        turn_plan=_updated_turn_plan(state, operations),
        original_route=current_route,
    )
