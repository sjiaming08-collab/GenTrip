from src.models.constraints import IntentDomain
from src.models.retrieval import DomainSpec, RetrievalFilters, RetrievalPlan
from src.services.postgis_poi_repository import _scope_cache_key, _scope_payload


def test_postgis_scope_cache_isolated_by_geo_query():
    xuhui = RetrievalPlan(
        raw_query="徐汇逛吃",
        filters=RetrievalFilters(district="徐汇区"),
        domains=[DomainSpec(domain=IntentDomain.DINING)],
    )
    huangpu = RetrievalPlan(
        raw_query="黄浦逛吃",
        filters=RetrievalFilters(district="黄浦区"),
        domains=[DomainSpec(domain=IntentDomain.DINING)],
    )

    assert _scope_payload(xuhui)["district"] == "徐汇区"
    assert _scope_cache_key(xuhui) != _scope_cache_key(huangpu)


def test_postgis_scope_cache_reuses_equivalent_geo_query():
    first = RetrievalPlan(
        raw_query="徐家汇喝咖啡",
        filters=RetrievalFilters(business_area="徐家汇", district="徐汇区"),
        domains=[DomainSpec(domain=IntentDomain.DINING)],
    )
    second = first.model_copy(update={"raw_query": "徐家汇附近咖啡"})

    assert _scope_cache_key(first) == _scope_cache_key(second)
