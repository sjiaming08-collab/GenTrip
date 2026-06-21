"""类目 taxonomy — 意图域 → POI 叶子类目。"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from ..models.retrieval import IntentDomain

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"
TAXONOMY_PATH = FIXTURES_DIR / "category_taxonomy.json"

DOMAIN_TO_PURPOSE_KEY = {
    IntentDomain.DINING: "DINING",
    IntentDomain.SIGHTSEEING: "SIGHTSEEING",
    IntentDomain.SHOPPING: "SHOPPING",
}


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


def domain_leaves(domain: IntentDomain) -> set[str]:
    key = DOMAIN_TO_PURPOSE_KEY[domain]
    leaves = _purpose_map().get(key, [])
    return set(leaves)


def all_retrieval_leaves() -> set[str]:
    leaves: set[str] = set()
    for domain in IntentDomain:
        leaves |= domain_leaves(domain)
    return leaves


def expand_categories(categories: list[str] | None) -> set[str] | None:
    """将 categories（叶子或 group）展开为叶子集合。"""
    if not categories:
        return None

    expanded: set[str] = set()
    groups = _groups()
    parents = _parents()

    for raw in categories:
        key = normalize_cuisine_term(raw)
        if key in groups:
            expanded.update(leaf for leaf, parent in parents.items() if parent == key)
        else:
            expanded.add(key)
    return expanded


def resolve_domain_leaves(
    domain: IntentDomain,
    categories: list[str] | None,
) -> set[str]:
    """单域类目：有 categories 则直接展开；否则使用该域全部叶子。"""
    allowed = domain_leaves(domain)
    expanded = expand_categories(categories)
    if expanded is None:
        return allowed
    return expanded & allowed if expanded else allowed


def widen_categories_to_parent_groups(categories: list[str] | None) -> list[str] | None:
    """叶子菜系无结果时，扩到父级 group（如 川菜 → 中餐）。"""
    if not categories:
        return None

    groups = _groups()
    parents = _parents()
    widened: list[str] = []
    for raw in categories:
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
    known = all_retrieval_leaves() | {"其他"}
    return sorted(poi_categories - known)


# --- 兼容旧测试（deprecated，检索主路径请用 resolve_domain_leaves）---

def expand_cuisines(preferred_cuisines: list[str] | None) -> set[str] | None:
    return expand_categories(preferred_cuisines)


def widen_preferred_to_parent_groups(preferred_cuisines: list[str] | None) -> list[str] | None:
    return widen_categories_to_parent_groups(preferred_cuisines)


def compute_final_leaves(
    *,
    domains: list[str] | None,
    preferred_cuisines: list[str] | None,
) -> set[str]:
    """兼容旧测试；新检索请用 resolve_domain_leaves + 多域 merge。"""
    from ..models.retrieval import DomainSpec

    specs: list[DomainSpec] = []
    for raw in domains or []:
        domain = IntentDomain(raw)
        categories = preferred_cuisines if domain == IntentDomain.DINING else None
        specs.append(DomainSpec(domain=domain, categories=categories))

    leaves: set[str] = set()
    for spec in specs:
        leaves |= resolve_domain_leaves(spec.domain, spec.categories)
    return leaves
