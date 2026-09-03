from src.graph.nodes.route_generate import _route_skeletons


def _shape(skeleton):
    return [(slot.domain, slot.categories) for slot in skeleton]


def test_explicit_cuisine_is_kept_in_multi_domain_skeleton():
    skeletons = _route_skeletons(["dining", "sightseeing"], 3, "先吃日料再看展")

    assert _shape(skeletons[0]) == [("dining", ("日料",)), ("sightseeing", ("文化艺术",))]


def test_explicit_mixed_skeleton_preserves_sightseeing_first_order():
    skeletons = _route_skeletons(["dining", "sightseeing"], 3, "先看展再喝咖啡")

    assert _shape(skeletons[0]) == [("sightseeing", ("文化艺术",)), ("dining", ("咖啡",))]


def test_exhibition_wording_keeps_museum_category():
    skeletons = _route_skeletons(["dining", "sightseeing"], 3, "看展览再喝咖啡")

    assert _shape(skeletons[0]) == [("sightseeing", ("博物馆",)), ("dining", ("咖啡",))]


def test_explicit_four_activity_request_builds_four_slots():
    skeletons = _route_skeletons(
        ["dining", "sightseeing"], 4, "包含观光和吃饭，尽量安排4个活动"
    )

    assert len(skeletons[0]) == 4
    assert {slot.domain for slot in skeletons[0]} == {"dining", "sightseeing"}


def test_explicit_cuisine_skeleton_is_padded_to_requested_activity_count():
    skeletons = _route_skeletons(
        ["dining", "sightseeing"], 3, "观光和吃饭，餐饮优先西餐，安排3个活动"
    )

    assert len(skeletons[0]) == 3
    assert any(slot.categories == ("西餐",) for slot in skeletons[0])


def test_alternative_cuisines_share_one_slot():
    skeletons = _route_skeletons(
        ["dining", "sightseeing"], 2, "包含观光和吃饭，餐饮可选西餐或本帮菜，安排2个活动"
    )

    assert len(skeletons[0]) == 2
    assert any(slot.categories == ("西餐", "本帮菜") for slot in skeletons[0])


def test_full_day_skeletons_do_not_include_compact_two_stop_alternative():
    skeletons = _route_skeletons(["sightseeing"], 5, "在黄浦区玩一天")

    assert skeletons
    assert all(len(skeleton) == 5 for skeleton in skeletons)


def test_full_day_explicit_activity_skeleton_is_padded_to_target():
    skeletons = _route_skeletons(
        ["sightseeing", "dining"], 5, "玩一天，先看展再喝咖啡"
    )

    assert skeletons
    assert all(len(skeleton) == 5 for skeleton in skeletons)
    assert _shape(skeletons[0])[:2] == [
        ("sightseeing", ("文化艺术",)),
        ("dining", ("咖啡",)),
    ]
