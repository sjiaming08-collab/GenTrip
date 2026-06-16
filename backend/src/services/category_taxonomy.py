"""类目 taxonomy — 用户/约束词 → POI 叶子类目集合。"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from ..models.constraints import TripPurpose

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"
TAXONOMY_PATH = FIXTURES_DIR / "category_taxonomy.json"


@lru_cache
def load_taxonomy() -> dict:
    with TAXONOMY_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _groups() -> set[str]:
    return set(load_taxonomy().get("groups") or [])


def _aliases() -> dict[str, str]:
    return load_taxonomy().get("aliases") or {}


def _parents() -> dict[str, str]:
    return load_taxonomy().get("parents") or {}


def _purpose_map() -> dict[str, list[str]]:
    return load_taxonomy().get("purpose_map") or {}


def normalize_cuisine_term(raw: str) -> str:
    term = raw.strip()
    if not term:
        return term
    return _aliases().get(term, term)


def purpose_allowed_leaves(purpose: str | None) -> set[str]:
    key = purpose or TripPurpose.MIXED.value
    leaves = _purpose_map().get(key)
    if leaves is None:
        leaves = _purpose_map().get(TripPurpose.MIXED.value, [])
    return set(leaves)


def resolve_purpose_leaves(
    purpose: str | None,
    activity_tags: list[str] | None,
) -> set[str]:
    """MIXED 时根据 activity_tags 推断有效叶子范围。"""
    if purpose and purpose != TripPurpose.MIXED.value:
        return purpose_allowed_leaves(purpose)

    if not activity_tags:
        return purpose_allowed_leaves(TripPurpose.MIXED.value)

    text = "".join(activity_tags)
    leaves: set[str] = set()
    if any(k in text for k in ("吃", "餐", "美食", "逛吃", "料理", "饭")):
        leaves |= purpose_allowed_leaves(TripPurpose.DINING.value)
    if any(k in text for k in ("买", "购物")):
        leaves |= purpose_allowed_leaves(TripPurpose.SHOPPING.value)
    if any(k in text for k in ("玩", "逛", "观光", "打卡", "展览", "博物馆")):
        leaves |= purpose_allowed_leaves(TripPurpose.SIGHTSEEING.value)

    if leaves:
        return leaves
    return purpose_allowed_leaves(TripPurpose.MIXED.value)


def expand_cuisines(preferred_cuisines: list[str] | None) -> set[str] | None:
    """将 preferred_cuisines 展开为叶子类目集合；None 表示不按菜系收窄。"""
    if not preferred_cuisines:
        return None

    expanded: set[str] = set()
    groups = _groups()
    parents = _parents()

    for raw in preferred_cuisines:
        key = normalize_cuisine_term(raw)
        if key in groups:
            expanded.update(leaf for leaf, parent in parents.items() if parent == key)
        else:
            expanded.add(key)
    return expanded


def compute_final_leaves(
    *,
    purpose: str | None,
    preferred_cuisines: list[str] | None,
    activity_tags: list[str] | None,
) -> set[str]:
    purpose_leaves = resolve_purpose_leaves(purpose, activity_tags)
    cuisine_leaves = expand_cuisines(preferred_cuisines)
    if cuisine_leaves is None:
        return purpose_leaves
    return cuisine_leaves & purpose_leaves


def widen_preferred_to_parent_groups(preferred_cuisines: list[str] | None) -> list[str] | None:
    """叶子菜系无结果时，扩到父级 group（如 川菜 → 中餐）。"""
    if not preferred_cuisines:
        return None

    groups = _groups()
    parents = _parents()
    widened: list[str] = []
    for raw in preferred_cuisines:
        key = normalize_cuisine_term(raw)
        if key in groups:
            widened.append(key)
            continue
        parent = parents.get(key)
        if parent:
            widened.append(parent)
    return widened or None


def parent_group_of_leaf(leaf: str) -> str | None:
    return _parents().get(leaf)


def validate_against_poi_categories(poi_categories: set[str]) -> list[str]:
    """返回 POI 中出现但未在 parents 中声明的餐饮类目。"""
    known = set(_parents()) | set(_purpose_map().get(TripPurpose.SIGHTSEEING.value, []))
    known |= set(_purpose_map().get(TripPurpose.SHOPPING.value, []))
    known.add("其他")
    return sorted(poi_categories - known)
