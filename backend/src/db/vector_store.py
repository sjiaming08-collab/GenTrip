"""pgvector 向量存储实现 — 实现 BaseVectorStore 接口"""

# TODO: 实现 BaseVectorStore
# from ..abstracts.vector_store import BaseVectorStore
# from pgvector.sqlalchemy import Vector
#
# class PgVectorStore(BaseVectorStore):
#     """PostgreSQL + pgvector 实现"""
#
#     async def store(self, doc_id, embedding, metadata=None): ...
#     async def search(self, query_embedding, top_k=5, filter_metadata=None):
#         # SELECT id, 1 - (embedding <=> :query) AS score, metadata
#         # FROM route_template
#         # ORDER BY embedding <=> :query
#         # LIMIT :top_k
#     async def delete(self, doc_id): ...
#     async def count(self): ...
raise NotImplementedError
