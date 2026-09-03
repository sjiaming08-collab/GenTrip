"""Expand GenTrip's deterministic Golden Sets to the documented coverage baseline.

The script is idempotent: generated cases replace cases with the same id and
leave hand-written cases untouched.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "backend" / "fixtures"


def merge(path: Path, generated: list[dict], *, replace_prefixes: tuple[str, ...] = ()) -> None:
    current = json.loads(path.read_text(encoding="utf-8"))
    generated_ids = {case["id"] for case in generated}
    merged = [
        case for case in current
        if case["id"] not in generated_ids
        and not any(case["id"].startswith(prefix) for prefix in replace_prefixes)
    ] + generated
    path.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def constraint_cases() -> list[dict]:
    cases: list[dict] = []

    starts = [
        ("midnight", "从0点开始", "00:00"),
        ("early_0730", "早上7:30开始", "07:30"),
        ("morning_cn", "上午九点开始", "09:00"),
        ("noon", "中午12点开始", "12:00"),
        ("afternoon_1305", "下午1:05开始", "13:05"),
        ("afternoon_cn", "下午三点开始", "15:00"),
        ("late_afternoon", "午后4点开始", "16:00"),
        ("evening_default", "晚上出发", "18:00"),
        ("evening_1830", "晚上6:30出发", "18:30"),
        ("night_default", "夜间出发", "19:00"),
        ("night_2130", "晚上9:30开始", "21:30"),
        ("clock_2355", "从23:55开始", "23:55"),
    ]
    for suffix, phrase, expected in starts:
        query = f"黄浦区{phrase}逛公园，预算100元，2小时"
        expect = {"district": "黄浦区", "start_at": expected, "time_budget_minutes": 120}
        if suffix == "afternoon_cn":
            query += "，晚上8点前回"
            expect["return_by"] = "20:00"
        cases.append({
            "id": f"edge_time_{suffix}",
            "query": query,
            "expect": expect,
        })

    durations = [
        ("half_hour", "半个小时", 30),
        ("ninety_minutes", "90分钟", 90),
        ("one_half", "一个半小时", 90),
        ("two_half", "两个半小时", 150),
        ("decimal", "2.5小时", 150),
        ("chinese_three", "三小时", 180),
        ("five_hours", "玩五个小时", 300),
        ("half_day", "半天", 240),
    ]
    for suffix, phrase, expected in durations:
        cases.append({
            "id": f"edge_duration_{suffix}",
            "query": f"徐汇区{phrase}逛街，预算160元",
            "expect": {"time_budget_minutes": expected, "domains": ["shopping"]},
        })

    budgets = [35, 49, 80, 99, 100, 150, 299, 500]
    for value in budgets:
        phrase = f"人均大约{value}元" if value % 2 else f"预算控制在{value}块"
        cases.append({
            "id": f"edge_budget_{value}",
            "query": f"静安区吃日料，{phrase}，2小时",
            "expect": {"budget_per_person": value, "preferred_cuisines": ["日料"], "domains": ["dining"]},
        })

    exclusions = [
        ("museum_park", "不要博物馆和公园", ["博物馆", "公园"]),
        ("museum_gallery", "不去博物馆和美术馆", ["博物馆", "美术馆"]),
        ("park_mall", "别去公园和商场", ["公园", "商场"]),
        ("exhibit_park", "跳过展览和绿地", ["公园", "展览"]),
        ("all_culture", "不想去博物馆、美术馆和展览", ["博物馆", "美术馆", "展览"]),
        ("museum_mall", "不要去博物馆和百货", ["博物馆", "商场"]),
        ("green_gallery", "不想去绿地和美术馆", ["公园", "美术馆"]),
        ("triple_mixed", "别去公园、商场和展览", ["公园", "展览", "商场"]),
    ]
    for suffix, phrase, expected in exclusions:
        cases.append({
            "id": f"multi_exclusion_{suffix}",
            "query": f"黄浦区{phrase}，想喝咖啡，3小时",
            "expect": {"excluded_categories": expected, "preferred_cuisines": ["咖啡"], "domains": ["dining"]},
        })

    cuisines = [
        ("chinese", "中国菜", "中餐"),
        ("shanghai", "上海菜", "本帮菜"),
        ("sichuan", "四川菜", "川菜"),
        ("cantonese", "广东菜", "粤菜"),
        ("japanese", "日本料理", "日料"),
        ("sushi", "寿司", "日料"),
        ("italian", "意大利餐", "西餐"),
        ("dessert", "甜点", "甜品"),
    ]
    for suffix, phrase, expected in cuisines:
        cases.append({
            "id": f"rare_preference_{suffix}",
            "query": f"浦东新区想吃{phrase}，人均180元，3小时",
            "expect": {"preferred_cuisines": [expected], "domains": ["dining"]},
        })

    domain_queries = [
        ("massage", "静安区做按摩放松三小时", ["leisure"]),
        ("fitness_meal", "徐汇区健身再吃饭四小时", ["dining", "leisure"]),
        ("mall_japanese", "黄浦区逛商场再吃日料四小时", ["dining", "shopping"]),
        ("exhibit_shop", "浦东新区看展再购物半天", ["sightseeing", "shopping"]),
        ("park_coffee", "徐汇区公园散步再喝咖啡三小时", ["dining", "sightseeing"]),
        ("family_meal", "浦东新区带孩子去亲子乐园再吃饭五小时", ["dining", "leisure"]),
    ]
    for suffix, query, expected in domain_queries:
        cases.append({"id": f"multi_domain_{suffix}", "query": query, "expect": {"domains": expected}})

    memories = [
        ("district", "预算改成90", {"district": "静安区", "time_budget_minutes": 240, "domains": ["shopping"]}, {"district": "静安区", "budget_per_person": 90, "time_budget_minutes": 240, "domains": ["shopping"]}),
        ("start", "再加一家甜品", {"district": "徐汇区", "start_at": "15:30", "time_budget_minutes": 180}, {"start_at": "15:30", "preferred_cuisines": ["甜品"]}),
        ("queue_zero", "换一家日料", {"district": "黄浦区", "queue_tolerance_minutes": 0}, {"queue_tolerance_minutes": 0, "preferred_cuisines": ["日料"]}),
        ("queue_twenty", "再安排一家火锅", {"district": "浦东新区", "queue_tolerance_minutes": 20}, {"queue_tolerance_minutes": 20, "preferred_cuisines": ["火锅"]}),
        ("excluded", "改成4小时", {"district": "黄浦区", "excluded_categories": ["博物馆", "公园"]}, {"time_budget_minutes": 240, "excluded_categories": ["博物馆", "公园"]}),
        ("cuisine", "预算100元", {"district": "静安区", "preferred_cuisines": ["川菜"], "domains": ["dining"]}, {"budget_per_person": 100, "preferred_cuisines": ["川菜"], "domains": ["dining"]}),
        ("duration", "下午4点开始", {"district": "徐汇区", "time_budget_minutes": 300}, {"start_at": "16:00", "time_budget_minutes": 300}),
        ("override", "换到黄浦区吃粤菜", {"district": "静安区", "preferred_cuisines": ["日料"]}, {"district": "黄浦区", "preferred_cuisines": ["粤菜"]}),
    ]
    for suffix, query, memory, expect in memories:
        cases.append({"id": f"memory_incremental_{suffix}", "query": query, "memory": memory, "expect": expect})

    assert len(cases) == 58
    return cases


def conversation_cases() -> list[dict]:
    districts = ["徐汇区", "静安区", "黄浦区", "浦东新区"]
    variants = [
        ("replace_add_delete_budget", ["把第1站换成日料", "再加一家甜品", "不要咖啡", "预算改成180元"]),
        ("preference_reversal", ["不想喝咖啡，换成日料", "还是想喝咖啡，换一家咖啡馆", "再加一家甜品", "去掉第2站"]),
        ("ordinal_edits", ["把第2站换成日料", "去掉第3站", "再加一家咖啡", "把第1站换成甜品"]),
        ("category_edits", ["不要商场", "再加一家日料", "不想去公园", "换一家甜品"]),
        ("multiple_adds", ["再加一家甜品", "再加一家日料", "去掉第2站", "预算改成200元"]),
        ("replace_chain", ["第一站换成日料", "第二站换成甜品", "第三站换成咖啡", "不要甜品"]),
        ("delete_restore", ["不要咖啡", "再加一家咖啡", "去掉第1站", "再加一家日料"]),
        ("cancel_and_replan", ["把第1站换成日料", "再加一家甜品", "取消当前路线生成", "重新规划黄浦区逛吃路线"]),
    ]
    cases: list[dict] = []
    for district in districts:
        for suffix, edits in variants:
            turns = [{
                "query": f"{district}下午两点逛商场、散步再喝咖啡，晚上8点前回，人均220元，5小时",
                "expect": {
                    "turn_mode": "plan",
                    "constraints": {"district": district, "budget_per_person": 220, "start_at": "14:00", "return_by": "20:00"},
                    "min_stops": 2,
                    "quality": {"min_score": 70, "max_leg_travel_min": 35, "require_unique_pois": True},
                },
            }]
            for index, query in enumerate(edits):
                if suffix == "cancel_and_replan" and query == "取消当前路线生成":
                    turns.append({
                        "query": query,
                        "action": "cancel_run",
                        "expect": {"run_status": "cancelled"},
                    })
                    continue
                turns.append({
                    "query": query,
                    "expect": {"turn_mode": "replan"},
                })
            cases.append({
                "id": f"generated_{district.removesuffix('区')}_{suffix}",
                "description": "完整路线上的替换、追加、删除、偏好反转、取消与重新规划分支。",
                "turns": turns,
            })
    assert len(cases) == 32
    return cases


def route_cases() -> list[dict]:
    districts = ["徐汇区", "静安区", "黄浦区", "浦东新区"]
    patterns = [
        ("leisure_food", "按摩放松再吃日料，5小时，人均260元", ["leisure", "dining"], [["日料"]]),
        ("sport_coffee", "健身再喝咖啡，4小时，人均180元", ["leisure", "dining"], [["咖啡"]]),
        ("shopping_food", "逛商场再吃饭，4小时，人均180元", ["shopping", "dining"], []),
        ("park_dessert", "公园散步再吃甜品，4小时，人均160元", ["sightseeing", "dining"], [["甜品"]]),
    ]
    cases: list[dict] = []
    for district in districts:
        for suffix, prompt, domains, groups in patterns:
            cases.append({
                "id": f"generated_route_{district.removesuffix('区')}_{suffix}",
                "query": f"{district}{prompt}",
                "description": "跨域多站点路线需满足预算、时间、类别覆盖和独立合法性校验。",
                "expect": {
                    "must_complete": True,
                    "must_be_legal": True,
                    "required_domains": domains,
                    "required_category_groups": groups,
                    "min_stops": 2,
                    "min_quality_score": 0.75,
                },
            })

    for district in districts:
        cases.append({
            "id": f"generated_fault_{district.removesuffix('区')}_travel_provider",
            "query": f"{district}逛商场再喝咖啡，4小时，人均180元",
            "description": "模拟外部交通 HTTP Provider 连接失败，验证本地估算回退后路线仍合法。",
            "simulate": {"travel_time_http_failure": True},
            "expect": {
                "must_complete": True,
                "must_be_legal": True,
                "required_domains": ["shopping", "dining"],
                "required_category_groups": [["咖啡"]],
                "required_tool_fallbacks": ["travel_time"],
                "min_stops": 2,
                "min_quality_score": 0.75,
            },
        })
    assert len(cases) == 20
    return cases


def main() -> None:
    merge(FIXTURES / "golden_constraint_cases.json", constraint_cases())
    merge(
        FIXTURES / "golden_conversations.json",
        conversation_cases(),
        replace_prefixes=("generated_",),
    )
    merge(
        FIXTURES / "route_eval_cases.json",
        route_cases(),
        replace_prefixes=("generated_route_", "generated_fault_"),
    )


if __name__ == "__main__":
    main()
