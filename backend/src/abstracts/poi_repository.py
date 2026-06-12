"""POI 数据仓库抽象 — 负责 POI 的结构化检索与排序"""

from abc import ABC, abstractmethod
from typing import Optional
from ..models.poi import PoiEntity, ScoredPoi
from ..models.intent import RouteIntent


class BasePoiRepository(ABC):
    """
    POI 数据访问抽象。

    实现类:
      - PostgresPoiRepository: SQLAlchemy + PostgreSQL
      - MockPoiRepository: 内存假数据 (测试)
    """

    @abstractmethod
    async def search_by_filters(
        self,
        district: Optional[str] = None,
        categories: Optional[list[str]] = None,
        max_price: Optional[int] = None,
        min_rating: float = 0.0,
        limit: int = 100,
    ) -> list[PoiEntity]:
        """结构化过滤检索"""
        ...

    @abstractmethod
    async def search_by_embedding(
        self,
        query_embedding: list[float],
        top_k: int = 30,
    ) -> list[PoiEntity]:
        """语义向量检索（用 pgvector 对 POI embedding 做 cosine 搜索）"""
        ...

    @abstractmethod
    async def get_by_id(self, poi_id: str) -> Optional[PoiEntity]:
        """按 ID 获取单个 POI"""
        ...

    @abstractmethod
    async def get_by_ids(self, poi_ids: list[str]) -> list[PoiEntity]:
        """按 ID 批量获取"""
        ...

    @abstractmethod
    async def rank(
        self,
        candidates: list[PoiEntity],
        intent: RouteIntent,
        user_lat: Optional[float] = None,
        user_lng: Optional[float] = None,
    ) -> list[ScoredPoi]:
        """
        多维排序：
        Score = 0.25*相关性 + 0.25*品质 + 0.20*个性化
               - 0.15*拥挤惩罚 - 0.15*距离惩罚
        """
        ...
