"""Mock POI 数据访问 — fixtures 使用点评 Tier-1 字段名。"""

import json
from functools import lru_cache
from pathlib import Path

from ..models.route import ScoredPoi
from ..services.poi_retrieval import RetrievalResultLegacy, retrieve_pois as _retrieve

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"
POIS_PATH = FIXTURES_DIR / "pois.json"
DISTRICTS = ["徐汇区", "静安区", "浦东新区", "黄浦区"]


@lru_cache
def load_pois() -> list[dict]:
    with POIS_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def parse_district(address: str) -> str:
    for district in DISTRICTS:
        if district in address:
            return district
    return ""


def retrieve_pois(
    district: str | None = None,
    limit: int = 10,
    *,
    domains: list[str] | None = None,
    preferred_cuisines: list[str] | None = None,
    budget_per_person: int | None = None,
) -> list[ScoredPoi]:
    return _retrieve(
        district=district,
        limit=limit,
        domains=domains,
        preferred_cuisines=preferred_cuisines,
        budget_per_person=budget_per_person,
    ).pois


def retrieve_pois_with_meta(
    district: str | None = None,
    limit: int = 10,
    *,
    domains: list[str] | None = None,
    preferred_cuisines: list[str] | None = None,
    budget_per_person: int | None = None,
) -> RetrievalResultLegacy:
    return _retrieve(
        district=district,
        limit=limit,
        domains=domains,
        preferred_cuisines=preferred_cuisines,
        budget_per_person=budget_per_person,
    )
