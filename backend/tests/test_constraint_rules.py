"""constraint_rules 单元测试。"""

from src.graph.state import build_initial_state
from src.models.constraints import TripPurpose
from src.services.constraint_rules import (
    detect_budget,
    detect_district,
    detect_minutes,
    detect_preferred_cuisines,
    detect_purpose,
    detect_return_by,
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


def test_detect_purpose():
    assert detect_purpose("静安购物") == TripPurpose.SHOPPING
    assert detect_purpose("徐汇逛吃") == TripPurpose.MIXED
    assert detect_purpose("想吃中餐") == TripPurpose.DINING


def test_detect_preferred_cuisines():
    assert detect_preferred_cuisines("想吃中餐") == ["中餐"]
    assert detect_preferred_cuisines("本帮菜") == ["本帮菜"]


def test_rule_based_extract_chinese_food():
    state = build_initial_state("徐汇区想吃中餐")
    constraints, _ = rule_based_extract(state)
    assert constraints.purpose == TripPurpose.DINING
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
    assert constraints.budget_per_person == 200
    assert constraints.time_budget_minutes == 180
    assert constraints.activity_tags == ["逛吃"]
    assert assumptions == []
