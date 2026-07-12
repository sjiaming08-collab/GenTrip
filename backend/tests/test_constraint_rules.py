"""constraint_rules 单元测试。"""

from src.graph.state import build_initial_state
from src.models.constraints import IntentDomain
from src.services.constraint_rules import (
    detect_budget,
    detect_district,
    detect_domains,
    detect_excluded_categories,
    detect_minutes,
    detect_preferred_cuisines,
    detect_queue_tolerance_minutes,
    detect_return_by,
    detect_start_at,
    rule_based_extract,
)


def test_detect_district_explicit():
    assert detect_district("徐汇逛吃") == "徐汇区"
    assert detect_district("想去静安区") == "静安区"


def test_detect_budget_and_minutes():
    assert detect_budget("预算200元") == 200
    assert detect_minutes("逛吃3小时") == 180
    assert detect_minutes("半天") == 240


def test_detect_return_by():
    assert detect_return_by("7点前回家") == "07:00"


def test_detect_start_and_queue_constraints():
    assert detect_start_at("下午三点出发去徐汇玩") == "15:00"
    assert detect_start_at("下午去玩") == "14:00"
    assert detect_queue_tolerance_minutes("排队不超过30分钟") == 30
    assert detect_queue_tolerance_minutes("不想排队") == 0


def test_detect_domains():
    assert detect_domains("静安购物") == [IntentDomain.SHOPPING]
    assert detect_domains("徐汇逛吃") == [IntentDomain.DINING, IntentDomain.SIGHTSEEING]
    assert detect_domains("想吃中餐") == [IntentDomain.DINING]


def test_detect_preferred_cuisines():
    assert detect_preferred_cuisines("想吃中餐") == ["中餐"]
    assert detect_preferred_cuisines("本帮菜") == ["本帮菜"]


def test_detect_excluded_categories():
    assert detect_excluded_categories("我不想去博物馆和公园") == ["博物馆", "公园"]


def test_rule_based_extract_chinese_food():
    state = build_initial_state("徐汇区想吃中餐")
    constraints, _ = rule_based_extract(state)
    assert constraints.domains == [IntentDomain.DINING]
    assert constraints.preferred_cuisines == ["中餐"]
    assert constraints.district == "徐汇区"


def test_rule_based_extract_defaults():
    state = build_initial_state("附近有什么好玩的")
    constraints, assumptions = rule_based_extract(state)

    assert constraints.district == "徐汇区"
    assert constraints.budget_per_person == 150
    assert constraints.time_budget_minutes == 180
    assert len(assumptions) == 3
    slots = {a.slot for a in assumptions}
    assert slots == {"district", "budget_per_person", "time_budget_minutes"}


def test_rule_based_extract_explicit():
    state = build_initial_state("黄浦区逛吃3小时预算200元")
    constraints, assumptions = rule_based_extract(state)

    assert constraints.district == "黄浦区"
    assert constraints.domains == [IntentDomain.DINING, IntentDomain.SIGHTSEEING]
    assert constraints.budget_per_person == 200
    assert constraints.time_budget_minutes == 180
    assert constraints.activity_tags == ["逛吃"]
    assert assumptions == []


def test_rule_based_extract_preserves_start_and_queue_constraints():
    constraints, assumptions = rule_based_extract(build_initial_state("下午两点出发，排队不超过30分钟，黄浦区逛吃"))

    assert constraints.start_at == "14:00"
    assert constraints.queue_tolerance_minutes == 30
    assert "start_at" not in {item.slot for item in assumptions}
    assert "queue_tolerance_minutes" not in {item.slot for item in assumptions}
