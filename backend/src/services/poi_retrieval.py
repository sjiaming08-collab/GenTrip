"""POI 召回 — 类目倒排、过滤管线与分级放宽。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from ..models.constraints import Assumption, TripPurpose
from ..models.route import ScoredPoi
from .category_taxonomy import (
    compute_final_leaves,
    widen_preferred_to_parent_groups,
)

MIN_CANDIDATES = 3


@dataclass
class RetrievalResult:
    pois: list[ScoredPoi]
    relax_step: str = "R0"
    final_leaves: list[str] = field(default_factory=list)
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


def to_scored_poi(poi: dict, rank_index: int) -> ScoredPoi:
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
    )


DISTRICTS = ["徐汇区", "静安区", "浦东新区", "黄浦区"]
FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"
POIS_PATH = FIXTURES_DIR / "pois.json"


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


def _sort_pois(pois: list[dict]) -> list[dict]:
    return sorted(pois, key=lambda p: float(p.get("star") or 0), reverse=True)


@dataclass
class _RelaxStep:
    name: str
    purpose: str | None
    preferred_cuisines: list[str] | None
    activity_tags: list[str] | None
    district: str | None
    budget_per_person: int | None
    assumption: Assumption | None = None


def _build_relax_plan(
    *,
    purpose: str | None,
    preferred_cuisines: list[str] | None,
    activity_tags: list[str] | None,
    district: str | None,
    budget_per_person: int | None,
) -> list[_RelaxStep]:
    widened = widen_preferred_to_parent_groups(preferred_cuisines)
    steps: list[_RelaxStep] = [
        _RelaxStep(
            "R0",
            purpose,
            preferred_cuisines,
            activity_tags,
            district,
            budget_per_person,
        ),
        _RelaxStep(
            "R1",
            purpose,
            preferred_cuisines,
            activity_tags,
            district,
            None,
            Assumption(
                slot="budget_per_person",
                assumed_value="ignored",
                source="poi_retrieve",
                message="候选不足，已忽略人均预算限制",
            )
            if budget_per_person is not None
            else None,
        ),
    ]

    if widened and widened != preferred_cuisines:
        steps.append(
            _RelaxStep(
                "R2",
                purpose,
                widened,
                activity_tags,
                district,
                None,
                Assumption(
                    slot="preferred_cuisines",
                    assumed_value=",".join(widened),
                    source="poi_retrieve",
                    message=f"指定菜系候选较少，已扩展为{'、'.join(widened)}",
                ),
            )
        )

    steps.extend(
        [
            _RelaxStep(
                "R3",
                purpose,
                None,
                activity_tags,
                district,
                None,
                Assumption(
                    slot="preferred_cuisines",
                    assumed_value="cleared",
                    source="poi_retrieve",
                    message="已按活动类型扩大餐饮/游玩类目范围",
                )
                if preferred_cuisines
                else None,
            ),
            _RelaxStep(
                "R4",
                purpose,
                None,
                activity_tags,
                None,
                None,
                Assumption(
                    slot="district",
                    assumed_value="citywide",
                    source="poi_retrieve",
                    message="本区同类 POI 较少，已扩展至全市",
                )
                if district
                else None,
            ),
            _RelaxStep(
                "R5",
                TripPurpose.MIXED.value,
                None,
                None,
                None,
                None,
                Assumption(
                    slot="purpose",
                    assumed_value=TripPurpose.MIXED.value,
                    source="poi_retrieve",
                    message="已放宽类目条件，按高评分 POI 推荐",
                ),
            ),
        ]
    )
    return steps


def retrieve_pois(
    *,
    district: str | None = None,
    limit: int = 10,
    purpose: str | None = None,
    preferred_cuisines: list[str] | None = None,
    activity_tags: list[str] | None = None,
    budget_per_person: int | None = None,
) -> RetrievalResult:
    steps = _build_relax_plan(
        purpose=purpose,
        preferred_cuisines=preferred_cuisines,
        activity_tags=activity_tags,
        district=district,
        budget_per_person=budget_per_person,
    )

    assumptions: list[Assumption] = []
    final_leaves: set[str] = set()
    filtered: list[dict] = []
    used_step = "R5"

    for step in steps:
        final_leaves = compute_final_leaves(
            purpose=step.purpose,
            preferred_cuisines=step.preferred_cuisines,
            activity_tags=step.activity_tags,
        )
        pool = _collect_by_leaves(final_leaves)
        filtered = _filter_pool(
            pool,
            district=step.district,
            budget_per_person=step.budget_per_person,
        )
        if len(filtered) >= MIN_CANDIDATES or step.name == "R5":
            used_step = step.name
            if step.assumption and step.name != "R0":
                assumptions.append(step.assumption)
            break

    if not filtered:
        filtered = _filter_pool(_online_pois(), district=None, budget_per_person=None)
        assumptions.append(
            Assumption(
                slot="category",
                assumed_value="fallback",
                source="poi_retrieve",
                message="类目过滤无结果，已回退为高评分 POI",
            )
        )

    sorted_pois = _sort_pois(filtered)
    scored = [to_scored_poi(poi, idx) for idx, poi in enumerate(sorted_pois[:limit])]

    return RetrievalResult(
        pois=scored,
        relax_step=used_step,
        final_leaves=sorted(final_leaves),
        assumptions=assumptions,
    )
