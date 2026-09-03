"""POI 检索计划 — 多意图域模型。"""

from typing import Optional

from pydantic import BaseModel, Field

from .constraints import Assumption, IntentDomain


class DomainSpec(BaseModel):
    """单个意图域的检索条件。"""

    domain: IntentDomain
    categories: Optional[list[str]] = None
    poi_names: list[str] = Field(default_factory=list)
    search_keywords: list[str] = Field(default_factory=list)


class RetrievalFilters(BaseModel):
    """跨域共享的过滤条件。"""

    city: Optional[str] = None
    district: Optional[str] = None
    business_area: Optional[str] = None
    center_lat: Optional[float] = None
    center_lng: Optional[float] = None
    radius_m: Optional[int] = None
    geo_scope: Optional[dict] = None
    budget_per_person: Optional[int] = None
    excluded_categories: list[str] = Field(default_factory=list)


class RetrievalPlan(BaseModel):
    """从用户提问解析出的检索计划。"""

    raw_query: str
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)
    domains: list[DomainSpec] = Field(default_factory=list)
    provider_query_limit: int | None = Field(default=None, ge=1, le=16)


class DomainRetrievalMeta(BaseModel):
    domain: IntentDomain
    relax_step: str
    categories_used: list[str] = Field(default_factory=list)
    candidate_count: int = 0


class RetrievalResult(BaseModel):
    """多域检索合并结果。"""

    pois: list
    assumptions: list[Assumption] = Field(default_factory=list)
    relaxed_constraints: list[str] = Field(default_factory=list)
    by_domain: list[DomainRetrievalMeta] = Field(default_factory=list)
    retrieval_trace: dict = Field(default_factory=dict)
    plan: Optional[RetrievalPlan] = None
