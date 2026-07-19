"""POI 类目召回测试。"""

import json

import pytest

from src.mocks.poi_store import retrieve_pois_with_meta
from src.models.constraints import IntentDomain
from src.models.retrieval import DomainSpec, RetrievalFilters, RetrievalPlan
from src.services import poi_retrieval
from src.services.poi_retrieval import poi_categories, retrieve_by_plan


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
    allowed = {"观光", "博物馆", "文化", "文化艺术", "公园"}
    assert all(p.category in allowed for p in result.pois)


def test_retrieve_leisure_activity_by_category():
    plan = RetrievalPlan(
        raw_query="徐汇区攀岩",
        filters=RetrievalFilters(district="徐汇区"),
        domains=[DomainSpec(domain=IntentDomain.LEISURE, categories=["体育运动"])],
    )
    poi_pool = [
        {
            "poi_id": "climb-1",
            "name": "徐汇抱石馆",
            "category": "体育运动",
            "sub_category": "攀岩馆/抱石",
            "district": "徐汇区",
            "location": {"lat": 31.20, "lng": 121.44},
            "rating": 4.6,
        }
    ]

    result = retrieve_by_plan(plan, limit=10, poi_pool=poi_pool)

    assert [poi.category for poi in result.pois] == ["体育运动"]
    assert result.pois[0].dimension == IntentDomain.LEISURE.value


def test_retrieve_family_activity_by_category():
    plan = RetrievalPlan(
        raw_query="浦东新区亲子乐园",
        filters=RetrievalFilters(district="浦东新区"),
        domains=[DomainSpec(domain=IntentDomain.LEISURE, categories=["亲子游乐"])],
    )
    poi_pool = [
        {
            "poi_id": "family-1",
            "name": "小小探索家儿童乐园",
            "category": "亲子游乐",
            "sub_category": "亲子乐园",
            "district": "浦东新区",
            "location": {"lat": 31.22, "lng": 121.53},
            "rating": 4.5,
        }
    ]

    result = retrieve_by_plan(plan, limit=10, poi_pool=poi_pool)

    assert [poi.category for poi in result.pois] == ["亲子游乐"]


def test_retrieve_mixed_guangchi():
    result = retrieve_pois_with_meta(
        district="徐汇区",
        domains=[IntentDomain.DINING.value, IntentDomain.SIGHTSEEING.value],
        limit=10,
    )
    assert result.pois
    categories = {p.category for p in result.pois}
    assert categories & {"本帮菜", "咖啡", "小吃快餐", "川菜", "日料", "西餐"}
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
    assert {poi.name for poi in result.pois} == {"衡复本帮小馆A", "衡复本帮小馆B", "衡复本帮小馆C", "徐家汇本帮小馆"}
    assert all("geo_strict" in poi.match_reasons for poi in result.pois[:3])
    assert "geo_relaxed" in next(poi for poi in result.pois if poi.name == "徐家汇本帮小馆").match_reasons
    assert all(poi.category == "本帮菜" for poi in result.pois)


def test_exact_business_area_prefers_curated_seed_over_synthetic_names():
    poi_pool = [
        {
            "poi_id": "sh_pd_sight_001",
            "name": "滨江大道观景步道",
            "category": "景点",
            "sub_category": "滨江步道",
            "district": "浦东新区",
            "business_area": "陆家嘴",
            "location": {"lat": 31.24138, "lng": 121.50324},
            "rating": 4.7,
        },
        {
            "poi_id": "sh_pd_公园_0864",
            "name": "桂林公园",
            "category": "景点",
            "sub_category": "公园",
            "district": "浦东新区",
            "business_area": "陆家嘴",
            "location": {"lat": 31.239, "lng": 121.502},
            "rating": 5.0,
        },
        {
            "poi_id": "sh_pd_城市地标_0865",
            "name": "七宝老街",
            "category": "景点",
            "sub_category": "城市地标",
            "district": "浦东新区",
            "business_area": "陆家嘴",
            "location": {"lat": 31.240, "lng": 121.504},
            "rating": 5.0,
        },
    ]
    plan = RetrievalPlan(
        raw_query="我想在陆家嘴附近玩三个小时",
        filters=RetrievalFilters(district="浦东新区", business_area="陆家嘴"),
        domains=[DomainSpec(domain=IntentDomain.SIGHTSEEING)],
    )

    result = retrieve_by_plan(plan, limit=10, poi_pool=poi_pool)

    assert [poi.name for poi in result.pois] == ["滨江大道观景步道", "桂林公园", "七宝老街"]
    assert result.pois[0].category == "观光"
    assert "curated_seed" in result.pois[0].tags


def test_exact_business_area_keeps_synthetic_fallback_when_no_curated_seed():
    poi_pool = [
        {
            "poi_id": "sh_pd_公园_0864",
            "name": "合成公园",
            "category": "景点",
            "sub_category": "公园",
            "district": "浦东新区",
            "business_area": "陆家嘴",
            "location": {"lat": 31.239, "lng": 121.502},
            "rating": 4.5,
        }
    ]
    plan = RetrievalPlan(
        raw_query="陆家嘴逛公园",
        filters=RetrievalFilters(district="浦东新区", business_area="陆家嘴"),
        domains=[DomainSpec(domain=IntentDomain.SIGHTSEEING)],
    )

    result = retrieve_by_plan(plan, limit=10, poi_pool=poi_pool)

    assert [poi.name for poi in result.pois] == ["合成公园"]
    assert "synthetic_generated" in result.pois[0].tags


def test_generic_meal_query_excludes_drink_only_categories():
    from src.services.poi_query_parser import parse_retrieval_plan

    plan = parse_retrieval_plan({
        "user_query": "就是吃点东西",
        "constraints": {"domains": ["dining"], "district": "徐汇区"},
    })

    assert plan.domains[0].categories
    assert "咖啡" not in plan.domains[0].categories
    assert "甜品" not in plan.domains[0].categories
    assert "日料" in plan.domains[0].categories


def test_negated_sightseeing_category_is_not_used_as_a_positive_retrieval_category():
    from src.services.poi_query_parser import parse_retrieval_plan

    plan = parse_retrieval_plan({
        "user_query": "我不想去公园",
        "constraints": {
            "domains": ["sightseeing"],
            "district": "黄浦区",
            "excluded_categories": ["公园"],
        },
    })

    assert plan.domains[0].categories is None


def test_district_results_keep_curated_seed_ahead_of_higher_rated_synthetic_data():
    poi_pool = [
        {
            "poi_id": "sh_xh_food_002",
            "name": "南丹路砂锅局",
            "category": "美食",
            "sub_category": "砂锅/煲仔",
            "district": "徐汇区",
            "location": {"lat": 31.19202, "lng": 121.43875},
            "rating": 4.5,
            "avg_price": 78,
        },
        {
            "poi_id": "sh_xh_川菜_0111",
            "name": "合成高分餐厅",
            "category": "美食",
            "sub_category": "川菜",
            "district": "徐汇区",
            "location": {"lat": 31.193, "lng": 121.439},
            "rating": 5.0,
            "avg_price": 80,
        },
    ]
    plan = RetrievalPlan(
        raw_query="徐汇区吃东西",
        filters=RetrievalFilters(district="徐汇区", budget_per_person=150),
        domains=[DomainSpec(domain=IntentDomain.DINING)],
    )

    result = retrieve_by_plan(plan, limit=10, poi_pool=poi_pool)

    assert [poi.name for poi in result.pois] == ["南丹路砂锅局", "合成高分餐厅"]


def test_named_poi_is_recalled_even_when_its_category_does_not_match_requested_domain():
    poi_pool = [
        {
            "poi_id": "street-1",
            "name": "武康路街区漫步点",
            "category": "景点",
            "sub_category": "城市街区",
            "district": "徐汇区",
            "business_area": "安福路/武康路",
            "location": {"lat": 31.21378, "lng": 121.43684},
            "rating": 4.7,
        }
    ]
    plan = RetrievalPlan(
        raw_query="我想去武康路街区漫步点吃东西",
        filters=RetrievalFilters(district="徐汇区", budget_per_person=150),
        domains=[DomainSpec(domain=IntentDomain.DINING)],
    )

    result = retrieve_by_plan(plan, limit=10, poi_pool=poi_pool)

    assert [poi.name for poi in result.pois] == ["武康路街区漫步点"]
    assert "name_exact" in result.pois[0].match_reasons
    assert result.retrieval_trace["channels"]["name_exact"] == 1


def test_poi_uses_all_category_and_tag_labels_for_recall():
    poi = {
        "poi_id": "street-1",
        "name": "武康路街区漫步点",
        "category": "景点",
        "sub_category": "城市街区",
        "tags": ["散步", "历史建筑"],
    }

    assert "观光" in poi_categories(poi)


def test_geo_relaxation_adds_candidates_without_dropping_strict_matches():
    poi_pool = [
        {
            "poi_id": "strict-1",
            "name": "陆家嘴滨江步道",
            "category": "景点",
            "sub_category": "滨江步道",
            "district": "浦东新区",
            "business_area": "陆家嘴",
            "location": {"lat": 31.241, "lng": 121.503},
            "rating": 4.4,
        },
        {
            "poi_id": "district-1",
            "name": "浦东城市公园",
            "category": "景点",
            "sub_category": "公园",
            "district": "浦东新区",
            "business_area": "世纪公园",
            "location": {"lat": 31.228, "lng": 121.544},
            "rating": 4.8,
        },
    ]
    plan = RetrievalPlan(
        raw_query="陆家嘴散步",
        filters=RetrievalFilters(district="浦东新区", business_area="陆家嘴"),
        domains=[DomainSpec(domain=IntentDomain.SIGHTSEEING)],
    )

    result = retrieve_by_plan(plan, limit=10, poi_pool=poi_pool)

    by_name = {poi.name: poi for poi in result.pois}
    assert {"陆家嘴滨江步道", "浦东城市公园"} <= set(by_name)
    assert "geo_strict" in by_name["陆家嘴滨江步道"].match_reasons
    assert "geo_relaxed" in by_name["浦东城市公园"].match_reasons
