"""从用户提问 + 约束解析 POI 检索计划（多意图域）。"""

from __future__ import annotations

from ..graph.state import GraphState
from ..models.constraints import IntentDomain
from ..models.retrieval import DomainSpec, RetrievalFilters, RetrievalPlan
from .constraint_rules import (
    DEFAULT_DISTRICT,
    detect_district,
    detect_preferred_cuisines,
)

_SIGHTSEEING_CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("博物馆", ["博物馆", "美术馆", "展览"]),
    ("公园", ["公园", "绿地"]),
    ("观光", ["外滩", "观光", "打卡"]),
    ("文化", ["文化", "历史"]),
]

_DINING_TRIGGER = ("吃", "餐", "美食", "饭", "料理", "逛吃", "聚餐", "宴请", "午餐", "晚餐")
_SIGHTSEEING_TRIGGER = ("逛", "玩", "游", "观光", "打卡", "展览", "博物馆", "公园", "景点", "逛逛")
_SHOPPING_TRIGGER = ("买", "购物", "逛街买", "商场")


def _detect_sightseeing_categories(query: str) -> list[str] | None:
    hits: list[str] = []
    for leaf, keywords in _SIGHTSEEING_CATEGORY_KEYWORDS:
        if any(k in query for k in keywords):
            hits.append(leaf)
    return hits or None


def _merge_categories(*groups: list[str] | None) -> list[str] | None:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        if not group:
            continue
        for item in group:
            if item not in seen:
                seen.add(item)
                merged.append(item)
    return merged or None


def _dining_from_query(query: str) -> DomainSpec | None:
    cuisines = detect_preferred_cuisines(query)
    if cuisines or any(k in query for k in _DINING_TRIGGER):
        return DomainSpec(
            domain=IntentDomain.DINING,
            categories=cuisines,
        )
    return None


def _sightseeing_from_query(query: str) -> DomainSpec | None:
    if not any(k in query for k in _SIGHTSEEING_TRIGGER):
        return None
    return DomainSpec(
        domain=IntentDomain.SIGHTSEEING,
        categories=_detect_sightseeing_categories(query),
    )


def _shopping_from_query(query: str) -> DomainSpec | None:
    if not any(k in query for k in _SHOPPING_TRIGGER):
        return None
    return DomainSpec(
        domain=IntentDomain.SHOPPING,
        categories=None,
    )


def _domain_specs_from_constraints(constraints: dict, query: str) -> list[DomainSpec]:
    """将 constraint_extract 输出的 domains 转为 DomainSpec。"""
    preferred = constraints.get("preferred_cuisines") or detect_preferred_cuisines(query)
    activity_tags = constraints.get("activity_tags") or []
    activity_text = "".join(activity_tags)
    sight_categories = _merge_categories(
        _detect_sightseeing_categories(query),
        _detect_sightseeing_categories(activity_text),
    )

    specs: list[DomainSpec] = []
    for raw in constraints.get("domains") or []:
        domain = IntentDomain(raw)
        categories = None
        if domain == IntentDomain.DINING:
            categories = preferred
        elif domain == IntentDomain.SIGHTSEEING:
            categories = sight_categories
        specs.append(DomainSpec(domain=domain, categories=categories))
    return specs


def _dedupe_domains(domains: list[DomainSpec]) -> list[DomainSpec]:
    by_domain: dict[IntentDomain, DomainSpec] = {}
    for spec in domains:
        existing = by_domain.get(spec.domain)
        if existing is None:
            by_domain[spec.domain] = spec
            continue
        merged_cats = _merge_categories(existing.categories, spec.categories)
        merged_names = list(dict.fromkeys(existing.poi_names + spec.poi_names))
        by_domain[spec.domain] = DomainSpec(
            domain=spec.domain,
            categories=merged_cats,
            poi_names=merged_names,
        )
    return list(by_domain.values())


def _default_domain(query: str) -> DomainSpec:
    if any(k in query for k in _SHOPPING_TRIGGER):
        return DomainSpec(domain=IntentDomain.SHOPPING, categories=None)
    if any(k in query for k in _DINING_TRIGGER):
        return DomainSpec(domain=IntentDomain.DINING, categories=detect_preferred_cuisines(query))
    return DomainSpec(domain=IntentDomain.SIGHTSEEING, categories=None)


def parse_retrieval_plan(state: GraphState) -> RetrievalPlan:
    query = state["user_query"]
    constraints = state.get("constraints") or {}

    district = constraints.get("district") or detect_district(query) or DEFAULT_DISTRICT
    budget = constraints.get("budget_per_person")

    if constraints.get("domains"):
        domains = _domain_specs_from_constraints(constraints, query)
    else:
        domains = list(filter(None, [
            _dining_from_query(query),
            _sightseeing_from_query(query),
            _shopping_from_query(query),
        ]))

    domains = _dedupe_domains(domains)

    if not domains:
        domains = [_default_domain(query)]

    return RetrievalPlan(
        raw_query=query,
        filters=RetrievalFilters(district=district, budget_per_person=budget),
        domains=domains,
    )
