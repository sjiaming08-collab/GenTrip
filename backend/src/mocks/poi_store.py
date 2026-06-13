"""Mock POI 数据访问 — fixtures 使用点评 Tier-1 字段名。"""

import json
from functools import lru_cache
from pathlib import Path

from ..models.route import ScoredPoi

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"
DISTRICTS = ["徐汇区", "静安区", "浦东新区", "黄浦区"]


@lru_cache
def load_pois() -> list[dict]:
    path = FIXTURES_DIR / "pois.json"
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def parse_district(address: str) -> str:
    for district in DISTRICTS:
        if district in address:
            return district
    return ""


def display_name(poi: dict) -> str:
    name = poi["name"]
    branch = (poi.get("branch_name") or "").strip()
    if branch:
        return f"{name}（{branch}）"
    return name


def to_scored_poi(poi: dict, rank_index: int) -> ScoredPoi:
    categories = poi.get("categories") or []
    category = categories[0] if categories else "其他"
    address = poi.get("address") or ""
    return ScoredPoi(
        poi_id=f"dp:{poi['openshopid']}",
        name=display_name(poi),
        category=category,
        district=parse_district(address),
        lat=float(poi["latitude"]),
        lng=float(poi["longitude"]),
        rating=float(poi.get("star") or 4.0),
        price_per_person=int(poi.get("avgprice") or 0),
        composite_score=max(0.0, 1.0 - rank_index * 0.05),
    )


def retrieve_pois(
    district: str | None = None,
    limit: int = 10,
) -> list[ScoredPoi]:
    pois = [p for p in load_pois() if p.get("openstatus") == 1]
    if district:
        pois = [p for p in pois if parse_district(p.get("address", "")) == district]
    pois = sorted(pois, key=lambda p: float(p.get("star") or 0), reverse=True)
    if not pois and district:
        pois = [p for p in load_pois() if p.get("openstatus") == 1]
        pois = sorted(pois, key=lambda p: float(p.get("star") or 0), reverse=True)

    result: list[ScoredPoi] = []
    for idx, poi in enumerate(pois[:limit]):
        result.append(to_scored_poi(poi, idx))
    return result
