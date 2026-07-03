"""POI 召回 — 多意图域分池检索与合并。"""

from __future__ import annotations

import json
import math
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
    all_retrieval_leaves,
    load_taxonomy,
    normalize_cuisine_term,
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
    budget_per_person: int | None
    assumption: Assumption | None = None


@dataclass
class _GeoRelaxStep:
    name: str
    district: str | None = None
    business_area: str | None = None
    center_lat: float | None = None
    center_lng: float | None = None
    radius_m: int | None = None
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


def _poi_id(poi: dict) -> str:
    raw = poi.get("openshopid") or poi.get("poi_id") or poi.get("id")
    if raw:
        return str(raw)
    lat, lng = _poi_lat_lng(poi)
    return f"{poi.get('name', 'poi')}:{lat}:{lng}"


def _poi_district(poi: dict) -> str:
    return poi.get("district") or parse_district(poi.get("address", ""), DISTRICTS)


def _poi_business_area(poi: dict) -> str:
    return poi.get("business_area") or ""


def _poi_lat_lng(poi: dict) -> tuple[float, float]:
    location = poi.get("location") or {}
    lat = poi.get("latitude", location.get("lat"))
    lng = poi.get("longitude", location.get("lng"))
    return float(lat or 0), float(lng or 0)


def _poi_rating(poi: dict) -> float:
    return float(poi.get("star") or poi.get("rating") or 4.0)


def _poi_price(poi: dict) -> int:
    return int(poi.get("avgprice") or poi.get("avg_price") or 0)


def _taxonomy_aliases() -> dict[str, str]:
    return load_taxonomy().get("aliases") or {}


def _category_from_text(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return "其他"

    normalized = normalize_cuisine_term(text)
    if normalized in all_retrieval_leaves():
        return normalized

    for alias, target in sorted(_taxonomy_aliases().items(), key=lambda item: len(item[0]), reverse=True):
        if alias and alias in text:
            return target

    if any(word in text for word in ("美术馆", "展览", "艺术馆")):
        return "博物馆"
    if "公园" in text:
        return "公园"
    if any(word in text for word in ("商场", "购物", "百货", "买手店")):
        return "购物"
    if any(word in text for word in ("景点", "观光", "地标")):
        return "观光"

    return text


def poi_primary_category(poi: dict) -> str:
    raw_categories: list[str] = []
    categories = poi.get("categories") or []
    if isinstance(categories, list):
        raw_categories.extend(str(item) for item in categories if item)
    if poi.get("sub_category"):
        raw_categories.insert(0, str(poi["sub_category"]))
    if poi.get("category"):
        raw_categories.append(str(poi["category"]))
    return _category_from_text(raw_categories[0]) if raw_categories else "其他"


def display_name(poi: dict) -> str:
    name = poi["name"]
    branch = (poi.get("branch_name") or poi.get("branch") or "").strip()
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
    lat, lng = _poi_lat_lng(poi)
    return ScoredPoi(
        poi_id=f"dp:{_poi_id(poi)}",
        name=display_name(poi),
        category=category,
        district=_poi_district(poi),
        lat=lat,
        lng=lng,
        rating=_poi_rating(poi),
        price_per_person=_poi_price(poi),
        composite_score=max(0.0, 1.0 - rank_index * 0.05),
        dimension=dimension.value,
    )


@lru_cache
def _load_pois() -> tuple[float, list[dict]]:
    mtime = os.path.getmtime(POIS_PATH)
    with POIS_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return mtime, data.get("pois") or []
    return mtime, data


def _online_pois() -> list[dict]:
    _, pois = _load_pois()
    return [
        p for p in pois
        if p.get("openstatus", 1) == 1 and p.get("status", "online") != "closed"
    ]


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
    _load_pois.cache_clear()


def _matches_budget(poi: dict, budget_per_person: int | None) -> bool:
    if budget_per_person is None:
        return True
    price = _poi_price(poi)
    if price == 0:
        return True
    return price <= int(budget_per_person * 1.2)


def _distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _matches_business_area(poi: dict, business_area: str) -> bool:
    area = _poi_business_area(poi)
    if not area:
        return False
    return area == business_area or area in business_area or business_area in area


def _matches_geo(poi: dict, geo: _GeoRelaxStep) -> bool:
    if geo.business_area:
        return _matches_business_area(poi, geo.business_area)
    if geo.center_lat is not None and geo.center_lng is not None and geo.radius_m:
        lat, lng = _poi_lat_lng(poi)
        if lat == 0 or lng == 0:
            return False
        return _distance_m(geo.center_lat, geo.center_lng, lat, lng) <= geo.radius_m
    if geo.district:
        return _poi_district(poi) == geo.district
    return True


def _filter_pool(
    pois: list[dict],
    *,
    geo: _GeoRelaxStep,
    budget_per_person: int | None,
) -> list[dict]:
    result = [p for p in pois if _matches_geo(p, geo)]
    if budget_per_person is not None:
        result = [p for p in result if _matches_budget(p, budget_per_person)]
    return result


def _collect_by_leaves(final_leaves: set[str]) -> list[dict]:
    index = get_category_index()
    seen: set[str] = set()
    collected: list[dict] = []
    for leaf in final_leaves:
        for poi in index.get(leaf, []):
            poi_id = _poi_id(poi)
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


def _sort_pois(pois: list[dict], geo: _GeoRelaxStep | None = None) -> list[dict]:
    if geo and geo.center_lat is not None and geo.center_lng is not None:
        return sorted(
            pois,
            key=lambda p: (
                _distance_m(geo.center_lat or 0, geo.center_lng or 0, *_poi_lat_lng(p)),
                -_poi_rating(p),
            ),
        )
    return sorted(pois, key=lambda p: _poi_rating(p), reverse=True)


def _geo_assumption(slot: str, value: str, message: str) -> Assumption:
    return Assumption(
        slot=slot,
        assumed_value=value,
        source="poi_retrieve",
        message=message,
    )


def _build_geo_relax_plan(plan: RetrievalPlan) -> list[_GeoRelaxStep]:
    filters = plan.filters
    steps: list[_GeoRelaxStep] = []

    if filters.business_area:
        steps.append(_GeoRelaxStep("G0", business_area=filters.business_area))

    if filters.center_lat is not None and filters.center_lng is not None and filters.radius_m:
        name = "G0" if not steps else f"G{len(steps)}"
        steps.append(
            _GeoRelaxStep(
                name,
                center_lat=filters.center_lat,
                center_lng=filters.center_lng,
                radius_m=filters.radius_m,
                assumption=None if name == "G0" else _geo_assumption(
                    "geo_scope",
                    "radius",
                    "商圈候选不足，已扩大到周边半径检索",
                ),
            )
        )

    if filters.district:
        name = "G0" if not steps else f"G{len(steps)}"
        steps.append(
            _GeoRelaxStep(
                name,
                district=filters.district,
                assumption=None if name == "G0" else _geo_assumption(
                    "geo_scope",
                    filters.district,
                    f"周边候选不足，已扩大到{filters.district}",
                ),
            )
        )

    if not steps:
        return [_GeoRelaxStep("G0")]

    steps.append(
        _GeoRelaxStep(
            f"G{len(steps)}",
            assumption=_geo_assumption(
                "geo_scope",
                "citywide",
                "当前范围候选较少，已扩展至全市",
            ),
        )
    )
    return steps


def _build_domain_relax_plan(
    spec: DomainSpec,
    *,
    budget_per_person: int | None,
) -> list[_DomainRelaxStep]:
    widened = widen_categories_to_parent_groups(spec.categories)
    steps: list[_DomainRelaxStep] = []

    if spec.domain == IntentDomain.DINING:
        steps.extend([
            _DomainRelaxStep("R0", spec.categories, budget_per_person),
            _DomainRelaxStep(
                "R1",
                spec.categories,
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
                    None,
                    Assumption(
                        slot="categories",
                        assumed_value=",".join(widened),
                        source="poi_retrieve",
                        message=f"饮食域指定类目候选较少，已扩展为{'、'.join(widened)}",
                    ),
                )
            )
        if spec.categories:
            steps.append(
                _DomainRelaxStep(
                    "R3",
                    None,
                    None,
                    Assumption(
                        slot="categories",
                        assumed_value="cleared",
                        source="poi_retrieve",
                        message="饮食域已扩大至全部餐饮类目",
                    ),
                )
            )
        return steps

    if spec.domain == IntentDomain.SIGHTSEEING:
        steps.append(_DomainRelaxStep("R0", spec.categories, None))
        if spec.categories:
            steps.append(
                _DomainRelaxStep(
                    "R1",
                    None,
                    None,
                    Assumption(
                        slot="categories",
                        assumed_value="cleared",
                        source="poi_retrieve",
                        message="游玩域已扩大至全部游玩类目",
                    ),
                )
            )
        return steps

    return [_DomainRelaxStep("R0", spec.categories, None)]


def _combined_step_name(domain_step: _DomainRelaxStep, geo_step: _GeoRelaxStep) -> str:
    if domain_step.name == "R0" and geo_step.name == "G0":
        return "R0"
    return f"{domain_step.name}-{geo_step.name}"


def _retrieve_one_domain(
    spec: DomainSpec,
    *,
    plan: RetrievalPlan,
    limit: int,
) -> _DomainRetrieveOutcome:
    geo_steps = _build_geo_relax_plan(plan)
    initial_geo = geo_steps[0]
    domain_steps = _build_domain_relax_plan(
        spec,
        budget_per_person=plan.filters.budget_per_person if spec.domain == IntentDomain.DINING else None,
    )

    pinned = _match_poi_names(spec.poi_names)
    pinned = _filter_pool(
        pinned,
        geo=initial_geo,
        budget_per_person=plan.filters.budget_per_person if spec.domain == IntentDomain.DINING else None,
    )

    assumptions: list[Assumption] = []
    final_leaves: set[str] = set()
    filtered: list[dict] = []
    used_step = _combined_step_name(domain_steps[-1], geo_steps[-1])
    used_geo = geo_steps[-1]

    for domain_step in domain_steps:
        final_leaves = resolve_domain_leaves(spec.domain, domain_step.categories)
        pool = _collect_by_leaves(final_leaves)
        for geo_step in geo_steps:
            filtered = _filter_pool(
                pool,
                geo=geo_step,
                budget_per_person=domain_step.budget_per_person,
            )
            if len(filtered) >= MIN_CANDIDATES or (domain_step is domain_steps[-1] and geo_step is geo_steps[-1]):
                used_step = _combined_step_name(domain_step, geo_step)
                used_geo = geo_step
                if domain_step.assumption and domain_step.name != "R0":
                    assumptions.append(domain_step.assumption)
                if geo_step.assumption and geo_step.name != "G0":
                    assumptions.append(geo_step.assumption)
                break
        else:
            continue
        break

    merged_pool = _sort_pois(_dedupe_poi_dicts(pinned + filtered), geo=used_geo)
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
        poi_id = _poi_id(poi)
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
            plan=plan,
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
