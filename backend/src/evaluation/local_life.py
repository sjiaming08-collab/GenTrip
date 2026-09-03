"""GenTrip-native local-life benchmark definitions and dataset builder."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


DISTRICTS = ("黄浦区", "徐汇区", "静安区", "浦东新区")
DIFFICULTIES = ("easy", "medium", "hard")
DATASET_CREATED_ON = "2026-08-17"


@dataclass(frozen=True)
class LocalLifeAgent:
    id: str
    name: str
    domain: str
    primary_phrase: str
    primary_group: tuple[str, ...]
    replacement_phrase: str
    replacement_group: tuple[str, ...]
    budget: int


AGENTS: tuple[LocalLifeAgent, ...] = (
    LocalLifeAgent("food", "美食餐饮规划", "dining", "吃本帮菜", ("本帮菜",), "日料", ("日料",), 220),
    LocalLifeAgent("city_walk", "城市观光规划", "sightseeing", "城市观光", ("观光",), "公园", ("公园",), 180),
    LocalLifeAgent("culture", "文化艺术规划", "sightseeing", "看艺术展", ("文化艺术",), "博物馆", ("博物馆",), 200),
    LocalLifeAgent("shopping", "商场购物规划", "shopping", "逛商场", ("商场", "购物"), "商场", ("商场", "购物"), 220),
    LocalLifeAgent("massage", "按摩足疗规划", "leisure", "做按摩", ("按摩足疗",), "足疗", ("按摩足疗",), 360),
    LocalLifeAgent("beauty", "美容美体规划", "leisure", "做美容", ("美容美体",), "美甲", ("美容美体",), 300),
    LocalLifeAgent("sports", "体育运动规划", "leisure", "去健身", ("体育运动",), "羽毛球", ("体育运动",), 260),
    LocalLifeAgent("gaming", "电玩游戏规划", "leisure", "玩电玩", ("电玩游戏",), "桌游", ("电玩游戏",), 240),
    LocalLifeAgent("performance", "演出娱乐规划", "leisure", "看演出", ("演出娱乐",), "电影院", ("演出娱乐",), 280),
    LocalLifeAgent("family", "亲子游乐规划", "leisure", "玩亲子乐园", ("亲子游乐",), "儿童乐园", ("亲子游乐",), 260),
)


def _split_for_district(district: str) -> str:
    if district in {"黄浦区", "徐汇区"}:
        return "development"
    if district == "静安区":
        return "validation"
    return "test"


def _expected_constraints(
    agent: LocalLifeAgent,
    district: str,
    difficulty: str,
) -> dict[str, Any]:
    if difficulty == "easy":
        return {
            "district": district,
            "time_budget_minutes": 180,
            "budget_per_person": agent.budget,
            "poi_count": 2,
            "domains": [agent.domain],
        }
    if difficulty == "medium":
        domains = list(dict.fromkeys((agent.domain, "dining")))
        return {
            "district": district,
            "time_budget_minutes": 300,
            "start_at": "16:00" if agent.id == "food" else "14:00",
            "queue_tolerance_minutes": 30,
            "budget_per_person": agent.budget,
            "poi_count": 3,
            "domains": domains,
        }
    domains = list(dict.fromkeys((agent.domain, "dining")))
    hard_poi_count = 3 if agent.id in {"massage", "beauty"} else 4
    return {
        "district": district,
        "time_budget_minutes": 360,
        "start_at": "15:00",
        "return_by": "21:00",
        "queue_tolerance_minutes": 20,
        "budget_per_person": agent.budget,
        "poi_count": hard_poi_count,
        "domains": domains,
        "excluded_categories": ["火锅"],
    }


def _query_and_groups(
    agent: LocalLifeAgent,
    district: str,
    difficulty: str,
) -> tuple[str, list[list[str]]]:
    if difficulty == "easy":
        return (
            f"请在{district}安排{agent.primary_phrase}的路线，总时长3小时，"
            f"人均预算不超过{agent.budget}元，安排2个地点。",
            [list(agent.primary_group)],
        )
    if agent.id == "food":
        if difficulty == "medium":
            return (
                f"{district}下午4点出发，先喝咖啡再吃日料，5小时，"
                f"人均{agent.budget}元，安排3个地点，排队不超过30分钟。",
                [["咖啡"], ["日料"]],
            )
        return (
            f"{district}下午3点出发，21点前回，不吃火锅，先喝咖啡再吃本帮菜，"
            f"人均{agent.budget}元，安排4个地点，排队最多20分钟。",
            [["本帮菜"], ["咖啡"]],
        )
    if difficulty == "medium":
        return (
            f"{district}下午2点出发，先{agent.primary_phrase}再喝咖啡，5小时，"
            f"人均{agent.budget}元，安排3个地点，排队不超过30分钟。",
            [list(agent.primary_group), ["咖啡"]],
        )
    hard_poi_count = _expected_constraints(agent, district, difficulty)["poi_count"]
    return (
        f"{district}下午3点出发，21点前回，不吃火锅，先{agent.primary_phrase}再吃日料，"
        f"人均{agent.budget}元，安排{hard_poi_count}个地点，排队最多20分钟。",
        [list(agent.primary_group), ["日料"]],
    )


def build_single_turn_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for agent in AGENTS:
        for district in DISTRICTS:
            for difficulty in DIFFICULTIES:
                query, groups = _query_and_groups(agent, district, difficulty)
                expected_constraints = _expected_constraints(agent, district, difficulty)
                cases.append({
                    "id": f"llb-{agent.id}-{DISTRICTS.index(district) + 1}-{difficulty}",
                    "split": _split_for_district(district),
                    "agent_id": agent.id,
                    "difficulty": difficulty,
                    "query": query,
                    "expect": {
                        "must_complete": True,
                        "must_be_legal": True,
                        "must_satisfy_expectations": True,
                        "required_domains": expected_constraints["domains"],
                        "required_category_groups": groups,
                        "min_stops": expected_constraints["poi_count"],
                        "min_quality_score": 0.72,
                        "expected_constraints": expected_constraints,
                    },
                })
    return cases


def build_conversations() -> list[dict[str, Any]]:
    conversations: list[dict[str, Any]] = []
    for index, agent in enumerate(AGENTS):
        district = "黄浦区"
        conversations.append({
            "id": f"llb-conversation-{agent.id}",
            "split": "development" if index < 5 else "validation" if index < 8 else "test",
            "agent_id": agent.id,
            "turns": [
                {
                    "query": (
                        f"请在{district}安排{agent.primary_phrase}的路线，5小时，"
                        f"人均{agent.budget}元，安排1个地点。"
                    ),
                    "expect": {
                        "turn_mode": "plan",
                        "required_category_groups": [list(agent.primary_group)],
                        "min_stops": 1,
                    },
                },
                {
                    "query": f"把第1站换成{agent.replacement_phrase}",
                    "expect": {
                        "turn_mode": "replan",
                        "operation": "replace",
                        "required_category_groups": [list(agent.replacement_group)],
                        "min_stops": 1,
                    },
                },
                {
                    "query": "在第1站后再加一个咖啡店",
                    "expect": {
                        "turn_mode": "replan",
                        "operation": "add",
                        "required_category_groups": [["咖啡"]],
                        "min_stops": 2,
                    },
                },
            ],
        })
    return conversations


def build_dataset() -> dict[str, Any]:
    cases = build_single_turn_cases()
    conversations = build_conversations()
    return {
        "metadata": {
            "name": "GenTrip LocalLifeBench",
            "version": "local-life-v1-20260817",
            "protocol": "gentrip-local-life-e2e-v1",
            "created_on": DATASET_CREATED_ON,
            "inspiration": "TravelPlanner-style stratified constraint and itinerary evaluation",
            "scope": "single-city local-life day planning and incremental replanning",
            "official_travelplanner_score": False,
            "poi_snapshot": "pois.json",
            "fixed_input_ts": "2026-08-18T03:00:00+00:00",
            "case_count": len(cases),
            "conversation_count": len(conversations),
            "conversation_turn_count": sum(len(item["turns"]) for item in conversations),
            "split_policy": "district-stratified single-turn cases; agent-stratified conversations",
            "quality_gate": {
                "minimum_constraint_pass_rate": 0.98,
                "minimum_single_end_to_end_pass_rate": 0.90,
                "minimum_mean_quality_score": 0.90,
                "minimum_conversation_turn_pass_rate": 0.95,
            },
        },
        "agents": [
            {
                **asdict(agent),
                "primary_group": list(agent.primary_group),
                "replacement_group": list(agent.replacement_group),
            }
            for agent in AGENTS
        ],
        "cases": cases,
        "conversations": conversations,
    }


def poi_coverage_issues(dataset: dict[str, Any], poi_fixture: dict[str, Any]) -> list[str]:
    """Verify that each scenario has enough native POIs in every district."""
    from ..services.poi_retrieval import poi_primary_category

    pois = poi_fixture.get("pois") or []
    issues: list[str] = []
    for agent in AGENTS:
        for district in DISTRICTS:
            names = {
                str(poi.get("name") or poi.get("poi_id") or "")
                for poi in pois
                if poi.get("district") == district
                and poi_primary_category(poi) in set(agent.primary_group)
            }
            count = len(names)
            if count < 2:
                issues.append(f"{agent.id}:{district}:primary_pois={count}<2")
    if len(dataset.get("agents") or []) != len(AGENTS):
        issues.append("agent_registry_mismatch")
    return issues
