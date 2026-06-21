"""POI 召回 — 多意图域分池检索与合并。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from ..models.constraints import Assumption
from ..models.retrieval import (
    DomainRetrievalMeta,
    DomainSpec,
    IntentDomain,
    RetrievalPlan,
    RetrievalResult,
)
from ..models.route import ScoredPoi
from .category_taxonomy import (
    resolve_domain_leaves,
    widen_categories_to_parent_groups,
)

MIN_CANDIDATES = 3
PER_DOMAIN_LIMIT = 8
MERGED_LIMIT = 20

DISTRICTS = ["徐汇区", "静安区", "浦东新区", "黄浦区"]
FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"
POIS_PATH = FIXTURES_DIR / "pois.json"


@dataclass
class _DomainRelaxStep:
    name: str
    categories: list[str] | None
    district: str | None
    budget_per_person: int | None
    assumption: Assumption | None = None


@dataclass
class _DomainRetrieveOutcome:
    pois: list[ScoredPoi]
    relax_step: str
    final_leaves: set[str]
    assumptions: list[Assumption] = field(default_factory=list)


def parse_district(address: str, districts: list[str]) -> str:
    for district in districts:
        if district in address:
            return district
    return ""


def poi_primary_category(poi: dict) -> str:
    categories = poi.get("categories") or []
    return categories[0] if categories else "其他"


def display_name(poi: dict) -> str:
    name = poi["name"]
    branch = (poi.get("branch_name") or "").strip()
    if branch:
        return f"{name}（{branch}）"
    return name


def to_scored_poi(
    poi: dict,
    rank_index: int,
    *,
    dimension: IntentDomain,
) -> ScoredPoi:
    category = poi_primary_category(poi)
    address = poi.get("address") or ""
    return ScoredPoi(
        poi_id=f"dp:{poi['openshopid']}",
        name=display_name(poi),
        category=category,
        district=parse_district(address, DISTRICTS),
        lat=float(poi["latitude"]),
        lng=float(poi["longitude"]),
        rating=float(poi.get("star") or 4.0),
        price_per_person=int(poi.get("avgprice") or 0),
        composite_score=max(0.0, 1.0 - rank_index * 0.05),
        dimension=dimension.value,
    )


@lru_cache
def _load_pois() -> tuple[float, list[dict]]:
    mtime = os.path.getmtime(POIS_PATH)
    with POIS_PATH.open(encoding="utf-8") as f:
        return mtime, json.load(f)


def _online_pois() -> list[dict]:
    _, pois = _load_pois()
    return [p for p in pois if p.get("openstatus") == 1]


@lru_cache
def _build_category_index(pois_json_mtime: float) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for poi in _online_pois():
        leaf = poi_primary_category(poi)
        index.setdefault(leaf, []).append(poi)
    return index


def get_category_index() -> dict[str, list[dict]]:
    mtime, _ = _load_pois()
    return _build_category_index(mtime)


def invalidate_index_cache() -> None:
    _build_category_index.cache_clear()


def _matches_budget(poi: dict, budget_per_person: int | None) -> bool:
    if budget_per_person is None:
        return True
    price = int(poi.get("avgprice") or 0)
    if price == 0:
        return True
    return price <= int(budget_per_person * 1.2)


def _filter_pool(
    pois: list[dict],
    *,
    district: str | None,
    budget_per_person: int | None,
) -> list[dict]:
    result = pois
    if district:
        result = [
            p for p in result if parse_district(p.get("address", ""), DISTRICTS) == district
        ]
    if budget_per_person is not None:
        result = [p for p in result if _matches_budget(p, budget_per_person)]
    return result


def _collect_by_leaves(final_leaves: set[str]) -> list[dict]:
    index = get_category_index()
    seen: set[str] = set()
    collected: list[dict] = []
    for leaf in final_leaves:
        for poi in index.get(leaf, []):
            poi_id = poi["openshopid"]
            if poi_id in seen:
                continue
            seen.add(poi_id)
            collected.append(poi)
    return collected


def _match_poi_names(poi_names: list[str]) -> list[dict]:
    if not poi_names:
        return []
    needles = [name.strip().lower() for name in poi_names if name.strip()]
    if not needles:
        return []
    matched: list[dict] = []
    for poi in _online_pois():
        haystack = display_name(poi).lower()
        if any(needle in haystack for needle in needles):
            matched.append(poi)
    return matched


def _sort_pois(pois: list[dict]) -> list[dict]:
    return sorted(pois, key=lambda p: float(p.get("star") or 0), reverse=True)


def _build_domain_relax_plan(
    spec: DomainSpec,
    *,
    district: str | None,
    budget_per_person: int | None,
) -> list[_DomainRelaxStep]:
    widened = widen_categories_to_parent_groups(spec.categories)
    steps: list[_DomainRelaxStep] = []

    if spec.domain == IntentDomain.DINING:
        steps.extend([
            _DomainRelaxStep("R0", spec.categories, district, budget_per_person),
            _DomainRelaxStep(
                "R1",
                spec.categories,
                district,
                None,
                Assumption(
                    slot="budget_per_person",
                    assumed_value="ignored",
                    source="poi_retrieve",
                    message="饮食域候选不足，已忽略人均预算限制",
                )
                if budget_per_person is not None
                else None,
            ),
        ])
        if widened and widened != spec.categories:
            steps.append(
                _DomainRelaxStep(
                    "R2",
                    widened,
                    district,
                    None,
                    Assumption(
                        slot="categories",
                        assumed_value=",".join(widened),
                        source="poi_retrieve",
                        message=f"饮食域指定类目候选较少，已扩展为{'、'.join(widened)}",
                    ),
                )
            )
        steps.extend([
            _DomainRelaxStep(
                "R3",
                None,
                district,
                None,
                Assumption(
                    slot="categories",
                    assumed_value="cleared",
                    source="poi_retrieve",
                    message="饮食域已扩大至全部餐饮类目",
                )
                if spec.categories
                else None,
            ),
            _DomainRelaxStep(
                "R4",
                None,
                None,
                None,
                Assumption(
                    slot="district",
                    assumed_value="citywide",
                    source="poi_retrieve",
                    message="饮食域本区候选较少，已扩展至全市",
                )
                if district
                else None,
            ),
        ])
        return steps

    if spec.domain == IntentDomain.SIGHTSEEING:
        return [
            _DomainRelaxStep("R0", spec.categories, district, None),
            _DomainRelaxStep(
                "R1",
                None,
                district,
                None,
                Assumption(
                    slot="categories",
                    assumed_value="cleared",
                    source="poi_retrieve",
                    message="游玩域已扩大至全部游玩类目",
                )
                if spec.categories
                else None,
            ),
            _DomainRelaxStep(
                "R2",
                None,
                None,
                None,
                Assumption(
                    slot="district",
                    assumed_value="citywide",
                    source="poi_retrieve",
                    message="游玩域本区候选较少，已扩展至全市",
                )
                if district
                else None,
            ),
        ]

    return [
        _DomainRelaxStep("R0", spec.categories, district, None),
        _DomainRelaxStep(
            "R1",
            None,
            None,
            None,
            Assumption(
                slot="district",
                assumed_value="citywide",
                source="poi_retrieve",
                message="购物域本区候选较少，已扩展至全市",
            )
            if district
            else None,
        ),
    ]


def _retrieve_one_domain(
    spec: DomainSpec,
    *,
    district: str | None,
    budget_per_person: int | None,
    limit: int,
) -> _DomainRetrieveOutcome:
    pinned = _match_poi_names(spec.poi_names)
    pinned = _filter_pool(
        pinned,
        district=district,
        budget_per_person=budget_per_person if spec.domain == IntentDomain.DINING else None,
    )

    steps = _build_domain_relax_plan(
        spec,
        district=district,
        budget_per_person=budget_per_person if spec.domain == IntentDomain.DINING else None,
    )
    assumptions: list[Assumption] = []
    final_leaves: set[str] = set()
    filtered: list[dict] = []
    used_step = steps[-1].name

    for step in steps:
        final_leaves = resolve_domain_leaves(spec.domain, step.categories)
        pool = _collect_by_leaves(final_leaves)
        filtered = _filter_pool(
            pool,
            district=step.district,
            budget_per_person=step.budget_per_person,
        )
        if len(filtered) >= MIN_CANDIDATES or step is steps[-1]:
            used_step = step.name
            if step.assumption and step.name != "R0":
                assumptions.append(step.assumption)
            break

    merged_pool = _sort_pois(_dedupe_poi_dicts(pinned + filtered))
    scored = [
        to_scored_poi(poi, idx, dimension=spec.domain)
        for idx, poi in enumerate(merged_pool[:limit])
    ]

    return _DomainRetrieveOutcome(
        pois=scored,
        relax_step=used_step,
        final_leaves=final_leaves,
        assumptions=assumptions,
    )


def _dedupe_poi_dicts(pois: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for poi in pois:
        poi_id = poi["openshopid"]
        if poi_id in seen:
            continue
        seen.add(poi_id)
        result.append(poi)
    return result


def retrieve_by_plan(plan: RetrievalPlan, *, limit: int = MERGED_LIMIT) -> RetrievalResult:
    if not plan.domains:
        return RetrievalResult(pois=[], plan=plan)

    per_domain_limit = max(PER_DOMAIN_LIMIT, limit // max(len(plan.domains), 1))
    all_pois: list[ScoredPoi] = []
    assumptions: list[Assumption] = []
    relaxed: list[str] = []
    by_domain: list[DomainRetrievalMeta] = []

    for spec in plan.domains:
        outcome = _retrieve_one_domain(
            spec,
            district=plan.filters.district,
            budget_per_person=plan.filters.budget_per_person,
            limit=per_domain_limit,
        )
        all_pois.extend(outcome.pois)
        assumptions.extend(outcome.assumptions)
        if outcome.relax_step != "R0":
            relaxed.append(f"{spec.domain.value}:{outcome.relax_step}")
        by_domain.append(
            DomainRetrievalMeta(
                domain=spec.domain,
                relax_step=outcome.relax_step,
                categories_used=sorted(outcome.final_leaves),
                candidate_count=len(outcome.pois),
            )
        )

    merged = _merge_scored_pois(all_pois, limit=limit)
    return RetrievalResult(
        pois=merged,
        assumptions=_merge_assumptions(assumptions),
        relaxed_constraints=relaxed,
        by_domain=by_domain,
        plan=plan,
    )


def _merge_scored_pois(pois: list[ScoredPoi], *, limit: int) -> list[ScoredPoi]:
    seen: set[str] = set()
    merged: list[ScoredPoi] = []
    for poi in sorted(pois, key=lambda item: item.rating, reverse=True):
        if poi.poi_id in seen:
            continue
        seen.add(poi.poi_id)
        merged.append(poi)
        if len(merged) >= limit:
            break
    return merged


def _merge_assumptions(items: list[Assumption]) -> list[Assumption]:
    by_slot: dict[str, Assumption] = {}
    for item in items:
        by_slot[item.slot] = item
    return list(by_slot.values())


# --- 兼容旧 API（tests / scripts）---

def retrieve_pois(
    *,
    district: str | None = None,
    limit: int = 10,
    domains: list[str] | None = None,
    preferred_cuisines: list[str] | None = None,
    budget_per_person: int | None = None,
) -> "RetrievalResultLegacy":
    from ..models.retrieval import RetrievalFilters, RetrievalPlan

    domain_specs: list[DomainSpec] = []
    for raw in domains or []:
        domain = IntentDomain(raw)
        categories = preferred_cuisines if domain == IntentDomain.DINING else None
        domain_specs.append(DomainSpec(domain=domain, categories=categories))

    plan = RetrievalPlan(
        raw_query="",
        filters=RetrievalFilters(district=district, budget_per_person=budget_per_person),
        domains=domain_specs or [DomainSpec(domain=IntentDomain.SIGHTSEEING, categories=None)],
    )
    result = retrieve_by_plan(plan, limit=limit)
    return RetrievalResultLegacy(
        pois=result.pois,
        relax_step=result.relaxed_constraints[0].split(":")[-1] if result.relaxed_constraints else "R0",
        final_leaves=sorted(
            {leaf for meta in result.by_domain for leaf in meta.categories_used}
        ),
        assumptions=result.assumptions,
    )


@dataclass
class RetrievalResultLegacy:
    pois: list[ScoredPoi]
    relax_step: str = "R0"
    final_leaves: list[str] = field(default_factory=list)
    assumptions: list[Assumption] = field(default_factory=list)
