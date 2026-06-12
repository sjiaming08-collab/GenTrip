"""知识库检索节点 — 语义搜索已缓存的路线模板

职责:
  1. 将 RouteIntent 编码为查询向量 (BaseEmbedder)
  2. 调用 BaseTemplateRepository.search_similar() 检索 Top-K 模板
  3. 输出 candidate_templates, query_embedding
"""

from ..state import GraphState


async def search_cache(state: GraphState) -> dict:
    """
    输入: state["route_intent"]
    输出: query_embedding, candidate_templates, current_phase="search_cache"
    依赖: BaseEmbedder, BaseTemplateRepository
    """
    # TODO: 实现
    # 1. search_text = f"{intent.purpose} {intent.constraints.district}
    #                    {','.join(intent.constraints.preferred_cuisines)}"
    # 2. query_vec = embedder.embed(search_text)
    # 3. templates = template_repo.search_similar(
    #        query_vec, top_k=5,
    #        district=intent.constraints.district,
    #        duration_min=intent.constraints.time_budget_minutes,
    #        budget=intent.constraints.budget_per_person)
    # 4. return {"query_embedding": query_vec,
    #            "candidate_templates": templates}
    raise NotImplementedError
