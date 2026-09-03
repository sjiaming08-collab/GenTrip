"""constraint_rules 单元测试。"""

from src.graph.state import build_initial_state
from src.models.constraints import IntentDomain
from src.services.constraint_rules import (
    detect_budget,
    detect_district,
    detect_domains,
    detect_excluded_categories,
    detect_minutes,
    detect_poi_count,
    detect_mobility_preferences,
    detect_location_mentions,
    derive_poi_count,
    detect_preferred_cuisines,
    detect_queue_tolerance_minutes,
    detect_return_by,
    detect_start_at,
    derive_time_budget_minutes,
    rule_based_extract,
)


def test_detect_district_explicit():
    assert detect_district("徐汇逛吃") == "徐汇区"
    assert detect_district("想去静安区") == "静安区"


def test_detect_named_nearby_location_without_guessing_district():
    assert detect_location_mentions("明天和女朋友在西湖附近玩一天") == ["西湖"]
    assert detect_location_mentions("杭州西湖附近喝咖啡") == ["西湖"]
    assert detect_location_mentions("附近玩一天") == []

    constraints, _ = rule_based_extract(
        build_initial_state("明天和女朋友在西湖附近玩一天")
    )
    assert constraints.location_mentions == ["西湖"]
    assert constraints.city is None
    assert constraints.district is None
    assert constraints.geo_relation == "nearby"


def test_detect_budget_and_minutes():
    assert detect_budget("预算200元") == 200
    assert detect_minutes("逛吃3小时") == 180
    assert detect_minutes("半天") == 240


def test_detect_explicit_poi_count_without_confusing_party_size():
    assert detect_poi_count("3人出行，尽量安排4个活动") == 4
    assert detect_poi_count("逛三个地点") == 3
    assert detect_poi_count("三个人玩五小时") is None


def test_detect_mobility_preferences():
    assert detect_mobility_preferences("带老人出门，尽量少走路") == ["少走路"]


def test_full_day_derives_a_five_stop_target():
    assert detect_minutes("在黄浦区玩一天") == 480
    assert detect_minutes("全天逛逛") == 480
    assert derive_poi_count("在黄浦区玩一天", 480, suggested_count=2) == 5


def test_explicit_stop_count_wins_over_full_day_derivation():
    assert derive_poi_count("玩一天，只安排2个地点", 480, suggested_count=5) == 2


def test_rule_based_extract_preserves_explicit_poi_count():
    constraints, _ = rule_based_extract(build_initial_state("黄浦区玩5小时，安排4个活动"))

    assert constraints.poi_count == 4
    assert constraints.anchor_count_explicit == 4
    assert constraints.poi_count_target == 4


def test_derive_time_budget_from_explicit_time_window():
    assert derive_time_budget_minutes("14:00", "18:00") == 240
    assert derive_time_budget_minutes("18:00", "14:00") is None


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
    assert detect_domains("我不去博物馆了，就是吃点东西，你重新为我规划一下呢") == [IntentDomain.DINING]
    assert detect_domains("徐汇区按摩足疗后去攀岩") == [IntentDomain.LEISURE]
    assert detect_domains("黄浦区玩电玩") == [IntentDomain.LEISURE]
    assert detect_domains("徐汇区逛商场") == [IntentDomain.SHOPPING]
    assert detect_domains("徐汇区吃火锅再散步") == [IntentDomain.DINING, IntentDomain.SIGHTSEEING]
    assert detect_domains("静安区逛书店再喝咖啡") == [IntentDomain.DINING, IntentDomain.SHOPPING]


def test_detect_preferred_cuisines():
    assert detect_preferred_cuisines("想吃中餐") == ["中餐"]
    assert detect_preferred_cuisines("本帮菜") == ["本帮菜"]


def test_detect_excluded_categories():
    assert detect_excluded_categories("我不想去博物馆和公园") == ["博物馆", "公园"]
    assert detect_excluded_categories("不去博物馆，想逛商场再喝咖啡") == ["博物馆"]
    assert detect_excluded_categories("不想去美术馆想吃日料") == ["美术馆"]


def test_rule_based_extract_chinese_food():
    state = build_initial_state("徐汇区想吃中餐")
    constraints, _ = rule_based_extract(state)
    assert constraints.domains == [IntentDomain.DINING]
    assert constraints.preferred_cuisines == ["中餐"]
    assert constraints.city == "上海市"
    assert constraints.district == "徐汇区"


def test_rule_based_extract_defaults():
    state = build_initial_state("附近有什么好玩的")
    constraints, assumptions = rule_based_extract(state)

    assert constraints.city == "上海"
    assert constraints.district is None
    assert constraints.budget_per_person == 150
    assert constraints.time_budget_minutes == 180
    assert len(assumptions) == 3
    slots = {a.slot for a in assumptions}
    assert slots == {"city", "budget_per_person", "time_budget_minutes"}


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


def test_rule_based_extract_derives_duration_from_start_and_return_by():
    constraints, assumptions = rule_based_extract(
        build_initial_state("黄浦区下午2点看展，18点前回")
    )

    assert constraints.start_at == "14:00"
    assert constraints.return_by == "18:00"
    assert constraints.time_budget_minutes == 240
    duration = next(item for item in assumptions if item.slot == "time_budget_minutes")
    assert duration.source == "derived_time_window"
    assert duration.overridable is False


def test_rule_based_extract_keeps_default_duration_when_only_return_by_is_given():
    constraints, assumptions = rule_based_extract(build_initial_state("黄浦区18点前回，喝咖啡"))

    assert constraints.time_budget_minutes == 180
    assert any(item.slot == "time_budget_minutes" and item.source == "scene_default" for item in assumptions)
