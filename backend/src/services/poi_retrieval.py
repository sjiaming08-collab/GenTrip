"""POI 召回 — 多意图域分池检索与合并。"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import httpx

from ..models.constraints import Assumption
from ..models.retrieval import (
    DomainRetrievalMeta,
    DomainSpec,
    IntentDomain,
    RetrievalPlan,
    RetrievalResult,
)
from ..models.route import ScoredPoi
from ..resources import fixture_path
from .category_taxonomy import (
    all_retrieval_leaves,
    load_taxonomy,
    normalize_cuisine_term,
    resolve_domain_leaves,
    widen_categories_to_parent_groups,
)
from .postgis_poi_repository import load_postgis_pois
from .amap_poi_provider import AmapPoiProviderError, load_amap_pois
from ..config import settings

logger = logging.getLogger(__name__)

MIN_CANDIDATES = 3
PER_DOMAIN_LIMIT = 8
MERGED_LIMIT = 20

DISTRICTS = ["徐汇区", "静安区", "浦东新区", "黄浦区"]
POIS_PATH = fixture_path("pois.json")
_POIS_PATH_OVERRIDE: ContextVar[Path | None] = ContextVar("poi_fixture_override", default=None)


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
    retrieval_trace: dict = field(default_factory=dict)


def parse_district(address: str | None, districts: list[str]) -> str:
    if not isinstance(address, str):
        return ""
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
    return poi.get("district") or poi.get("area") or parse_district(poi.get("address", ""), DISTRICTS)


def _poi_business_area(poi: dict) -> str:
    return poi.get("business_area") or ""


def _poi_lat_lng(poi: dict) -> tuple[float, float]:
    location = poi.get("location") or {}
    lat = poi.get("latitude", location.get("lat"))
    lng = poi.get("longitude", location.get("lng"))
    return float(lat or 0), float(lng or 0)


def _poi_rating(poi: dict) -> float:
    raw = poi.get("star")
    if raw is None:
        raw = poi.get("rating")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _poi_price(poi: dict) -> int:
    return int(poi.get("avgprice") or poi.get("avg_price") or 0)


def _poi_queue_wait_min(poi: dict) -> int:
    raw = poi.get("queue_minutes")
    if isinstance(raw, dict):
        raw = raw.get("weekday", 0)
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return 0


def _poi_data_tier(poi: dict) -> str:
    """Classify local fixture records without trusting synthetic place names."""
    explicit = str(poi.get("data_tier") or "").strip()
    if explicit:
        return explicit
    poi_id = _poi_id(poi)
    if re.fullmatch(r"sh_[a-z]{2}_(?:food|cafe|leisure|sight)_\d{3}", poi_id):
        return "curated_seed"
    if re.fullmatch(r"sh_[a-z]{2}_.+_\d{4}", poi_id):
        return "synthetic_generated"
    return "unknown"


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
    if any(word in text for word in ("砂锅", "煲仔", "米线", "面馆", "面条")):
        return "小吃快餐"
    if "公园" in text:
        return "公园"
    if any(word in text for word in ("商场", "购物", "百货", "买手店")):
        return "购物"
    if any(word in text for word in ("景点", "观光", "地标", "滨江", "步道", "历史建筑", "街区", "散步")):
        return "观光"

    return text


def poi_categories(poi: dict) -> set[str]:
    specific_categories: list[str] = []
    categories = poi.get("categories") or []
    if isinstance(categories, list):
        specific_categories.extend(str(item) for item in categories if item)
    if poi.get("sub_category"):
        specific_categories.append(str(poi["sub_category"]))
    mapped_specific = {_category_from_text(raw) for raw in specific_categories}
    specific_leaves = {
        category for category in mapped_specific if category in all_retrieval_leaves()
    }
    if specific_leaves:
        return specific_leaves

    raw_categories: list[str] = []
    if poi.get("category"):
        raw_categories.append(str(poi["category"]))
    raw_categories.extend(str(item) for item in poi.get("tags") or [] if item)
    mapped = {_category_from_text(raw) for raw in raw_categories}
    return {category for category in mapped if category in all_retrieval_leaves()} or {"其他"}


def poi_primary_category(poi: dict) -> str:
    for key in ("sub_category", "category"):
        category = _category_from_text(str(poi.get(key) or ""))
        if category in all_retrieval_leaves():
            return category
    categories = poi_categories(poi)
    return sorted(categories)[0]


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
    match_reasons: list[str] | None = None,
) -> ScoredPoi:
    category = poi_primary_category(poi)
    lat, lng = _poi_lat_lng(poi)
    data_tier = _poi_data_tier(poi)
    tags = [str(item) for item in poi.get("tags") or [] if item]
    if data_tier not in tags:
        tags.append(data_tier)
    reasons = list(dict.fromkeys(match_reasons or []))
    tags.extend(f"match:{reason}" for reason in reasons if f"match:{reason}" not in tags)
    name_bonus = 1.0 if "name_exact" in reasons else 0.0
    return ScoredPoi(
        poi_id=f"{_poi_source_prefix(poi)}:{_poi_id(poi)}",
        name=display_name(poi),
        category=category,
        district=_poi_district(poi),
        lat=lat,
        lng=lng,
        rating=_poi_rating(poi),
        price_per_person=_poi_price(poi),
        composite_score=max(0.0, 1.0 - rank_index * 0.05) + name_bonus,
        dimension=dimension.value,
        queue_wait_min=_poi_queue_wait_min(poi),
        opening_hours=[dict(item) for item in poi.get("opening_hours") or [] if isinstance(item, dict)],
        opening_hours_text=str(poi.get("opening_hours_text") or "") or None,
        ugc_summary=str(poi.get("ugc_summary") or "") or None,
        tags=tags,
        match_reasons=reasons,
    )


def _poi_source_prefix(poi: dict) -> str:
    source = str(poi.get("source") or "").strip()
    return "dp" if not source or source == "fixture" else source


def _active_pois_path() -> Path:
    return _POIS_PATH_OVERRIDE.get() or POIS_PATH


@contextmanager
def use_poi_fixture(path: Path):
    """Use an isolated fixture in the current async context."""
    resolved = path.resolve()
    if not resolved.exists():
        raise FileNotFoundError(resolved)
    token = _POIS_PATH_OVERRIDE.set(resolved)
    try:
        yield
    finally:
        _POIS_PATH_OVERRIDE.reset(token)


@lru_cache
def _load_pois(path_value: str | None = None) -> tuple[float, list[dict]]:
    path = Path(path_value) if path_value else _active_pois_path()
    mtime = os.path.getmtime(path)
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return mtime, data.get("pois") or []
    return mtime, data


def _online_pois() -> list[dict]:
    _, pois = _load_pois(str(_active_pois_path()))
    return [
        p for p in pois
        if p.get("openstatus", 1) == 1 and p.get("status", "online") != "closed"
    ]


@lru_cache
def _build_category_index(path_value: str, pois_json_mtime: float) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for poi in _online_pois():
        for leaf in poi_categories(poi):
            index.setdefault(leaf, []).append(poi)
    return index


def get_category_index() -> dict[str, list[dict]]:
    path_value = str(_active_pois_path())
    mtime, _ = _load_pois(path_value)
    return _build_category_index(path_value, mtime)


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
    if geo.business_area and not _matches_business_area(poi, geo.business_area):
        return False
    if geo.center_lat is not None and geo.center_lng is not None and geo.radius_m:
        lat, lng = _poi_lat_lng(poi)
        if lat == 0 or lng == 0:
            return False
        if _distance_m(geo.center_lat, geo.center_lng, lat, lng) > geo.radius_m:
            return False
    if geo.district and _poi_district(poi) != geo.district:
        return False
    return True


def _filter_pool(
    pois: list[dict],
    *,
    geo: _GeoRelaxStep,
    budget_per_person: int | None,
    excluded_categories: list[str] | None = None,
) -> list[dict]:
    result = [p for p in pois if _matches_geo(p, geo)]
    if budget_per_person is not None:
        result = [p for p in result if _matches_budget(p, budget_per_person)]
    if excluded_categories:
        result = [
            poi for poi in result
            if not any(excluded in category or category in excluded for category in poi_categories(poi) for excluded in excluded_categories)
        ]
    return result


def _collect_by_leaves(final_leaves: set[str], poi_pool: list[dict] | None = None) -> list[dict]:
    if poi_pool is not None:
        return [poi for poi in poi_pool if poi_categories(poi) & final_leaves]
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


def _poi_search_names(poi: dict) -> list[str]:
    values = [str(poi.get("name") or ""), display_name(poi)]
    aliases = poi.get("aliases") or poi.get("alias") or []
    if isinstance(aliases, str):
        aliases = [aliases]
    values.extend(str(alias) for alias in aliases if alias)
    return list(dict.fromkeys(value.strip() for value in values if value and value.strip()))


def _normalize_search_text(value: str) -> str:
    return re.sub(r"[\s()（）,，.。·_-]+", "", value).casefold()


def _match_poi_names(poi_names: list[str], poi_pool: list[dict] | None = None) -> list[dict]:
    if not poi_names:
        return []
    needles = [_normalize_search_text(name) for name in poi_names if name.strip()]
    if not needles:
        return []
    matched: list[dict] = []
    for poi in poi_pool if poi_pool is not None else _online_pois():
        names = [_normalize_search_text(value) for value in _poi_search_names(poi)]
        if any(needle in haystack for needle in needles for haystack in names):
            matched.append(poi)
    return matched


def _match_query_poi_names(query: str, poi_pool: list[dict] | None = None) -> list[dict]:
    haystack = _normalize_search_text(query)
    if len(haystack) < 2:
        return []
    matched: list[dict] = []
    for poi in poi_pool if poi_pool is not None else _online_pois():
        if any(len(name := _normalize_search_text(value)) >= 2 and name in haystack for value in _poi_search_names(poi)):
            matched.append(poi)
    return matched


def _sort_pois(
    pois: list[dict],
    geo: _GeoRelaxStep | None = None,
    match_reasons: dict[str, list[str]] | None = None,
) -> list[dict]:
    def quality_rank(poi: dict) -> int:
        return {"curated_seed": 0, "unknown": 1, "synthetic_generated": 2}.get(_poi_data_tier(poi), 1)

    def match_rank(poi: dict) -> int:
        reasons = set((match_reasons or {}).get(_poi_id(poi), []))
        if "name_exact" in reasons:
            return 0
        if "geo_strict" in reasons and "category_strict" in reasons:
            return 1
        if "geo_strict" in reasons:
            return 2
        return 3

    if geo and geo.center_lat is not None and geo.center_lng is not None:
        return sorted(
            pois,
            key=lambda p: (
                match_rank(p),
                quality_rank(p),
                _distance_m(geo.center_lat or 0, geo.center_lng or 0, *_poi_lat_lng(p)),
                -_poi_rating(p),
                _poi_id(p),
            ),
        )
    return sorted(
        pois,
        key=lambda p: (match_rank(p), quality_rank(p), -_poi_rating(p), _poi_id(p)),
    )


def _prefer_curated_data(pois: list[dict], geo: _GeoRelaxStep) -> list[dict]:
    """Use synthetic records only when curated coverage is insufficient."""
    curated = [poi for poi in pois if _poi_data_tier(poi) == "curated_seed"]
    if geo.business_area:
        return curated or pois
    if len(curated) >= MIN_CANDIDATES:
        return curated
    return pois


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
                district=filters.district,
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
    poi_pool: list[dict] | None = None,
) -> _DomainRetrieveOutcome:
    geo_steps = _build_geo_relax_plan(plan)
    initial_geo = geo_steps[0]
    domain_steps = _build_domain_relax_plan(
        spec,
        budget_per_person=plan.filters.budget_per_person if spec.domain == IntentDomain.DINING else None,
    )

    hard_budget = plan.filters.budget_per_person if spec.domain == IntentDomain.DINING else None
    pinned = _match_poi_names(spec.poi_names, poi_pool)
    pinned.extend(_match_query_poi_names(plan.raw_query, poi_pool))
    pinned = _filter_pool(
        _dedupe_poi_dicts(pinned),
        geo=_GeoRelaxStep("named"),
        budget_per_person=hard_budget,
        excluded_categories=plan.filters.excluded_categories,
    )

    # Recall is additive: strict matches remain in the pool while broader
    # category/geo passes contribute lower-priority candidates.
    by_id: dict[str, dict] = {}
    reasons: dict[str, list[str]] = {}
    channel_counts = {"name_exact": 0, "category_strict": 0, "geo_strict": 0, "geo_relaxed": 0}

    def add(items: list[dict], *reason_values: str) -> None:
        for poi in items:
            poi_id = _poi_id(poi)
            by_id[poi_id] = poi
            bucket = reasons.setdefault(poi_id, [])
            for reason in reason_values:
                if reason not in bucket:
                    bucket.append(reason)

    if pinned:
        add(pinned, "name_exact")
        channel_counts["name_exact"] = len(pinned)

    strict_count = 0
    first_nonempty: tuple[_DomainRelaxStep, _GeoRelaxStep] | None = None
    strict_leaves = resolve_domain_leaves(spec.domain, domain_steps[0].categories)
    strict_category_available = bool(_collect_by_leaves(strict_leaves, poi_pool))
    for domain_index, domain_step in enumerate(domain_steps):
        leaves = resolve_domain_leaves(spec.domain, domain_step.categories)
        # A user-specified category is a semantic constraint, not a hint.
        # Broaden geography first; only expand categories when no strict
        # category POI exists anywhere in the source.
        if domain_index > 0 and leaves != strict_leaves and strict_category_available:
            continue
        pool = _collect_by_leaves(leaves, poi_pool)
        for geo_index, geo_step in enumerate(geo_steps):
            filtered = _filter_pool(
                pool,
                geo=geo_step,
                budget_per_person=domain_step.budget_per_person,
                excluded_categories=plan.filters.excluded_categories,
            )
            if filtered and first_nonempty is None:
                first_nonempty = (domain_step, geo_step)
            reason_values = [
                "category_strict" if domain_index == 0 else "category_relaxed",
                "geo_strict" if geo_index == 0 else "geo_relaxed",
            ]
            if domain_step.budget_per_person is None and hard_budget is not None:
                reason_values.append("budget_relaxed")
            add(filtered, *reason_values)
            if domain_index == 0:
                channel_counts["category_strict"] += len(filtered)
            if geo_index == 0:
                channel_counts["geo_strict"] += len(filtered)
            else:
                channel_counts["geo_relaxed"] += len(filtered)
            if domain_index == 0 and geo_index == 0:
                strict_count = len(filtered)

    used_domain, used_geo = first_nonempty or (domain_steps[0], initial_geo)
    used_step = _combined_step_name(used_domain, used_geo)
    assumptions: list[Assumption] = []
    if strict_count == 0:
        if used_domain.assumption:
            assumptions.append(used_domain.assumption)
        if used_geo.assumption:
            assumptions.append(used_geo.assumption)

    merged_candidates = list(by_id.values())
    district = str(plan.filters.district or "")
    scope_type = str((plan.filters.geo_scope or {}).get("scope_type") or "")
    district_is_explicit = bool(district and scope_type in {"", "district"})
    if district_is_explicit:
        merged_candidates = [
            poi for poi in merged_candidates if _poi_district(poi) == district
        ]
    merged_pool = _sort_pois(merged_candidates, geo=initial_geo, match_reasons=reasons)
    scored = [
        to_scored_poi(poi, idx, dimension=spec.domain, match_reasons=reasons.get(_poi_id(poi), []))
        for idx, poi in enumerate(merged_pool[:limit])
    ]

    return _DomainRetrieveOutcome(
        pois=scored,
        relax_step=used_step,
        final_leaves=strict_leaves,
        assumptions=assumptions,
        retrieval_trace={
            "domain": spec.domain.value,
            "strict_candidate_count": strict_count,
            "channels": channel_counts,
            "candidate_count_before_limit": len(merged_pool),
            "named_poi_ids": [_poi_id(poi) for poi in pinned],
        },
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


def retrieve_by_plan(
    plan: RetrievalPlan,
    *,
    limit: int = MERGED_LIMIT,
    poi_pool: list[dict] | None = None,
) -> RetrievalResult:
    if not plan.domains:
        return RetrievalResult(pois=[], plan=plan)

    per_domain_limit = max(PER_DOMAIN_LIMIT, limit // max(len(plan.domains), 1))
    all_pois: list[ScoredPoi] = []
    assumptions: list[Assumption] = []
    relaxed: list[str] = []
    by_domain: list[DomainRetrievalMeta] = []
    traces: list[dict] = []

    for spec in plan.domains:
        outcome = _retrieve_one_domain(
            spec,
            plan=plan,
            limit=per_domain_limit,
            poi_pool=poi_pool,
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
        traces.append(outcome.retrieval_trace)

    merged = _merge_scored_pois(all_pois, limit=limit)
    return RetrievalResult(
        pois=merged,
        assumptions=_merge_assumptions(assumptions),
        relaxed_constraints=relaxed,
        by_domain=by_domain,
        retrieval_trace={
            "channels": {
                key: sum(int((trace.get("channels") or {}).get(key, 0)) for trace in traces)
                for key in {key for trace in traces for key in (trace.get("channels") or {})}
            },
            "strict_candidate_count": sum(int(trace.get("strict_candidate_count") or 0) for trace in traces),
            "candidate_count_before_limit": sum(int(trace.get("candidate_count_before_limit") or 0) for trace in traces),
            "domains": traces,
        },
        plan=plan,
    )


async def retrieve_by_plan_async(plan: RetrievalPlan, *, limit: int = MERGED_LIMIT) -> tuple[RetrievalResult, str, bool, bool]:
    """Retrieve from the configured source with deterministic local fallback."""
    if _POIS_PATH_OVERRIDE.get() is not None:
        return retrieve_by_plan(plan, limit=limit), "fixture:override", False, False

    if settings.poi_provider == "mock":
        return retrieve_by_plan(plan, limit=limit), "fixture", False, False

    if settings.poi_provider == "amap":
        try:
            poi_pool, cache_hit = await load_amap_pois(plan)
            if poi_pool:
                return retrieve_by_plan(plan, limit=limit, poi_pool=poi_pool), "amap", False, cache_hit
            logger.warning("amap_poi_fallback reason=empty_result")
        except (AmapPoiProviderError, httpx.HTTPError, ValueError) as exc:
            logger.warning("amap_poi_fallback reason=%s", type(exc).__name__)

        poi_pool, cache_hit = await load_postgis_pois(settings.database_url, plan)
        if poi_pool:
            return retrieve_by_plan(plan, limit=limit, poi_pool=poi_pool), "postgis", True, cache_hit
        return retrieve_by_plan(plan, limit=limit), "fixture", True, False

    poi_pool, cache_hit = await load_postgis_pois(settings.database_url, plan)
    if poi_pool is None:
        return retrieve_by_plan(plan, limit=limit), "fixture", True, False
    return retrieve_by_plan(plan, limit=limit, poi_pool=poi_pool), "postgis", False, cache_hit


def _merge_scored_pois(pois: list[ScoredPoi], *, limit: int) -> list[ScoredPoi]:
    def tier_rank(poi: ScoredPoi) -> int:
        if "curated_seed" in poi.tags:
            return 0
        if "synthetic_generated" in poi.tags:
            return 2
        return 1

    seen: set[str] = set()
    merged: list[ScoredPoi] = []
    for poi in sorted(
        pois,
        key=lambda item: (tier_rank(item), -item.composite_score, -item.rating, item.poi_id),
    ):
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
