"""BGE Embedder 实现 — 实现 BaseEmbedder 接口

使用 sentence-transformers 加载 BGE-small-zh-v1.5 模型。
首次加载会下载 ~100MB 模型文件，之后缓存在本地。
"""

# TODO: 实现 BaseEmbedder
# from sentence_transformers import SentenceTransformer
# from ..abstracts.embedder import BaseEmbedder
#
# class BgeEmbedder(BaseEmbedder):
#     """BGE-small-zh-v1.5 本地向量编码器"""
#
#     MODEL_NAME = "BAAI/bge-small-zh-v1.5"
#
#     def __init__(self):
#         self._model = SentenceTransformer(self.MODEL_NAME)
#
#     @property
#     def dimension(self) -> int:
#         return 512  # BGE-small-zh
#
#     def embed(self, text: str) -> list[float]:
#         return self._model.encode(text, normalize_embeddings=True).tolist()
#
#     def embed_batch(self, texts: list[str]) -> list[list[float]]:
#         return self._model.encode(
#             texts, normalize_embeddings=True,
#             show_progress_bar=False
#         ).tolist()
raise NotImplementedError
