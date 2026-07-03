"""POI 类目召回测试。"""

from src.mocks.poi_store import retrieve_pois_with_meta
from src.models.constraints import TripPurpose


def test_retrieve_chinese_cuisine_in_xuhui():
    result = retrieve_pois_with_meta(
        district="徐汇区",
        purpose=TripPurpose.DINING.value,
        preferred_cuisines=["中餐"],
        limit=10,
    )
    assert result.pois
    assert result.relax_step == "R0"
    allowed = {"本帮菜", "火锅", "小吃快餐", "川菜", "粤菜", "烧烤"}
    assert all(p.category in allowed for p in result.pois)


def test_retrieve_sichuan_widens_when_empty():
    result = retrieve_pois_with_meta(
        district="徐汇区",
        purpose=TripPurpose.DINING.value,
        preferred_cuisines=["川菜"],
        limit=10,
    )
    assert result.pois
    assert result.relax_step in {"R2", "R3", "R4", "R5"}
    assert any(a.slot == "preferred_cuisines" for a in result.assumptions)


def test_retrieve_museum_sightseeing():
    result = retrieve_pois_with_meta(
        district="徐汇区",
        purpose=TripPurpose.SIGHTSEEING.value,
        limit=10,
    )
    assert result.pois
    allowed = {"观光", "博物馆", "文化", "公园"}
    assert all(p.category in allowed for p in result.pois)


def test_retrieve_mixed_guangchi():
    result = retrieve_pois_with_meta(
        district="徐汇区",
        purpose=TripPurpose.MIXED.value,
        activity_tags=["逛吃"],
        limit=10,
    )
    assert result.pois
    categories = {p.category for p in result.pois}
    assert categories & {"本帮菜", "咖啡", "小吃快餐"}
    assert categories & {"观光", "博物馆", "文化", "公园"}
