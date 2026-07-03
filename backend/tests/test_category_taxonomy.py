"""category_taxonomy 单元测试。"""

from src.services.category_taxonomy import (
    compute_final_leaves,
    expand_cuisines,
    normalize_cuisine_term,
    widen_preferred_to_parent_groups,
)


def test_normalize_aliases():
    assert normalize_cuisine_term("中国菜") == "中餐"
    assert normalize_cuisine_term("本帮") == "本帮菜"


def test_expand_chinese_group():
    leaves = expand_cuisines(["中餐"])
    assert "本帮菜" in leaves
    assert "火锅" in leaves
    assert "小吃快餐" in leaves
    assert "西餐" not in leaves


def test_expand_leaf():
    assert expand_cuisines(["川菜"]) == {"川菜"}


def test_compute_final_leaves_dining_without_preferred():
    leaves = compute_final_leaves(
        purpose="DINING",
        preferred_cuisines=None,
        activity_tags=None,
    )
    assert "本帮菜" in leaves
    assert "博物馆" not in leaves


def test_compute_final_leaves_chinese():
    leaves = compute_final_leaves(
        purpose="DINING",
        preferred_cuisines=["中餐"],
        activity_tags=None,
    )
    assert leaves == {"本帮菜", "火锅", "小吃快餐", "川菜", "粤菜", "烧烤"}


def test_widen_sichuan_to_chinese():
    assert widen_preferred_to_parent_groups(["川菜"]) == ["中餐"]
