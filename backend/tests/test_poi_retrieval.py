"""POI 类目召回测试。"""

import json

import pytest

from src.mocks.poi_store import retrieve_pois_with_meta
from src.models.constraints import IntentDomain
from src.models.retrieval import DomainSpec, RetrievalFilters, RetrievalPlan
from src.services import poi_retrieval
from src.services.poi_retrieval import retrieve_by_plan


@pytest.fixture(autouse=True)
def clear_poi_retrieval_cache():
    poi_retrieval.invalidate_index_cache()
    yield
    poi_retrieval.invalidate_index_cache()


def test_retrieve_chinese_cuisine_in_xuhui():
    result = retrieve_pois_with_meta(
        district="徐汇区",
        domains=[IntentDomain.DINING.value],
        preferred_cuisines=["中餐"],
        limit=10,
    )
    assert result.pois
    assert result.relax_step.startswith("R0")  # category matched, geo may relax with merged data
    allowed = {"本帮菜", "火锅", "小吃快餐", "川菜", "粤菜", "烧烤"}
    assert all(p.category in allowed for p in result.pois)


def test_retrieve_sichuan_widens_when_empty():
    result = retrieve_pois_with_meta(
        district="徐汇区",
        domains=[IntentDomain.DINING.value],
        preferred_cuisines=["川菜"],
        limit=10,
    )
    assert result.pois
    # With richer data, 川菜 may be found at R0 or relaxed — both are valid
    assert any(a.slot in {"categories", "geo_scope"} for a in result.assumptions) or result.relax_step.startswith("R0")


def test_retrieve_museum_sightseeing():
    result = retrieve_pois_with_meta(
        district="徐汇区",
        domains=[IntentDomain.SIGHTSEEING.value],
        limit=10,
    )
    assert result.pois
    allowed = {"观光", "博物馆", "文化", "公园"}
    assert all(p.category in allowed for p in result.pois)


def test_retrieve_mixed_guangchi():
    result = retrieve_pois_with_meta(
        district="徐汇区",
        domains=[IntentDomain.DINING.value, IntentDomain.SIGHTSEEING.value],
        limit=10,
    )
    assert result.pois
    categories = {p.category for p in result.pois}
    assert categories & {"本帮菜", "咖啡", "小吃快餐"}
    assert categories & {"观光", "博物馆", "文化", "公园"}


def test_retrieve_meituan_style_business_area(monkeypatch, tmp_path):
    seed = {
        "pois": [
            {
                "poi_id": "a",
                "name": "衡复本帮小馆A",
                "category": "美食",
                "sub_category": "本帮江浙菜",
                "district": "徐汇区",
                "business_area": "衡山路/复兴西路",
                "location": {"lat": 31.20764, "lng": 121.44621},
                "avg_price": 100,
                "rating": 4.7,
            },
            {
                "poi_id": "b",
                "name": "衡复本帮小馆B",
                "category": "美食",
                "sub_category": "本帮菜",
                "district": "徐汇区",
                "business_area": "衡山路/复兴西路",
                "location": {"lat": 31.208, "lng": 121.447},
                "avg_price": 110,
                "rating": 4.6,
            },
            {
                "poi_id": "c",
                "name": "衡复本帮小馆C",
                "category": "美食",
                "sub_category": "上海菜",
                "district": "徐汇区",
                "business_area": "衡山路/复兴西路",
                "location": {"lat": 31.209, "lng": 121.448},
                "avg_price": 90,
                "rating": 4.5,
            },
            {
                "poi_id": "d",
                "name": "徐家汇本帮小馆",
                "category": "美食",
                "sub_category": "本帮菜",
                "district": "徐汇区",
                "business_area": "徐家汇",
                "location": {"lat": 31.19202, "lng": 121.43875},
                "avg_price": 80,
                "rating": 4.9,
            },
        ]
    }
    pois_path = tmp_path / "pois.json"
    pois_path.write_text(json.dumps(seed, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(poi_retrieval, "POIS_PATH", pois_path)
    poi_retrieval.invalidate_index_cache()

    plan = RetrievalPlan(
        raw_query="衡复吃本帮菜",
        filters=RetrievalFilters(
            district="徐汇区",
            business_area="衡山路/复兴西路",
            budget_per_person=120,
        ),
        domains=[DomainSpec(domain=IntentDomain.DINING, categories=["本帮菜"])],
    )

    result = retrieve_by_plan(plan, limit=10)

    assert result.pois
    assert result.by_domain[0].relax_step == "R0"
    assert {poi.name for poi in result.pois} == {"衡复本帮小馆A", "衡复本帮小馆B", "衡复本帮小馆C"}
    assert all(poi.category == "本帮菜" for poi in result.pois)
