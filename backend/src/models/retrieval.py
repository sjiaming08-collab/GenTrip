"""POI 检索计划 — 多意图域模型。"""

from typing import Optional

from pydantic import BaseModel, Field

from .constraints import Assumption, IntentDomain


class DomainSpec(BaseModel):
    """单个意图域的检索条件。"""

    domain: IntentDomain
    categories: Optional[list[str]] = None
    poi_names: list[str] = Field(default_factory=list)


class RetrievalFilters(BaseModel):
    """跨域共享的过滤条件。"""

    district: Optional[str] = None
    budget_per_person: Optional[int] = None


class RetrievalPlan(BaseModel):
    """从用户提问解析出的检索计划。"""

    raw_query: str
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)
    domains: list[DomainSpec] = Field(default_factory=list)


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
    plan: Optional[RetrievalPlan] = None
