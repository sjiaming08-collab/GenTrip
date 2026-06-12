"""向量存储抽象 — 负责语义向量的存储与相似度检索"""

from abc import ABC, abstractmethod
from typing import Any, Optional


class BaseVectorStore(ABC):
    """
    向量存储 + 语义检索抽象。

    实现类:
      - PgVectorStore: PostgreSQL + pgvector (生产)
      - InMemoryVectorStore: 内存实现 (测试/开发)
    """

    @abstractmethod
    async def store(
        self,
        doc_id: str,
        embedding: list[float],
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """存储一条向量记录"""
        ...

    @abstractmethod
    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        filter_metadata: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """
        余弦相似度搜索，返回 top_k 条。
        每条返回: {"id": str, "score": float, "metadata": dict}
        """
        ...

    @abstractmethod
    async def delete(self, doc_id: str) -> None:
        """删除一条向量记录"""
        ...

    @abstractmethod
    async def count(self) -> int:
        """向量总条数"""
        ...
