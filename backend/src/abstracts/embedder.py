"""向量编码器抽象 — 负责将文本转为 Embedding 向量"""

from abc import ABC, abstractmethod


class BaseEmbedder(ABC):
    """
    文本 → 向量编码抽象。

    实现类:
      - BgeEmbedder: 本地 BGE-small-zh-v1.5 (sentence-transformers)
      - OpenAIEmbedder: OpenAI-compatible Embedding API (fallback)
    """

    @property
    @abstractmethod
    def dimension(self) -> int:
        """向量维度（BGE-small-zh 为 512）"""
        ...

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """单文本编码 → 向量"""
        ...

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量编码 → 向量列表"""
        ...
