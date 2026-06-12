"""路线模板仓库抽象 — 负责知识库模板的存储与语义检索"""

from abc import ABC, abstractmethod
from typing import Optional
from ..models.template import RouteTemplate
from ..models.route import RouteFeedback


class BaseTemplateRepository(ABC):
    """
    路线模板 (知识库) 数据访问抽象。

    实现类:
      - PostgresTemplateRepository: SQLAlchemy + pgvector
      - MockTemplateRepository: 内存实现 (测试)
    """

    @abstractmethod
    async def search_similar(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        district: Optional[str] = None,
        duration_min: Optional[int] = None,
        budget: Optional[int] = None,
    ) -> list[RouteTemplate]:
        """
        语义 + 结构化混合检索：
        1. pgvector cosine 相似度 → top-k
        2. 结构化字段 (district, duration, budget) 过滤
        """
        ...

    @abstractmethod
    async def get_by_id(self, template_id: str) -> Optional[RouteTemplate]:
        """按 ID 获取单个模板"""
        ...

    @abstractmethod
    async def save(self, template: RouteTemplate) -> RouteTemplate:
        """保存/更新模板（含 embedding）"""
        ...

    @abstractmethod
    async def update_after_feedback(
        self, template_id: str, feedback: RouteFeedback
    ) -> None:
        """
        反馈后更新模板质量指标：
        - avg_rating: EMA(α=0.2)
        - use_count += 1
        - avg_rating < 3.0 → active = False (淘汰)
        """
        ...

    @abstractmethod
    async def list_active(
        self, limit: int = 200
    ) -> list[RouteTemplate]:
        """获取所有活跃模板（按 avg_rating 排序）"""
        ...
