"""完整生成节点 (完整 LLM) — matchScore < 0.75 时执行

职责:
  1. 检索 Top-30 POI 候选 (BasePoiRepository)
  2. LLM 从零规划完整路线
  3. 异步写入模板库 (asyncSaveAsTemplate)

延迟目标: ~5s, Token: ~3000
"""

from ..state import GraphState


async def full_generate(state: GraphState) -> dict:
    """
    输入: state["route_intent"], state["query_embedding"],
          state["user_lat"], state["user_lng"]
    输出: route_result (source=FRESH_GENERATED), candidate_pois,
          current_phase="full_generate"
    副作用: 异步存入 RouteTemplate 知识库
    依赖: BaseLLMClient, BasePoiRepository, BaseTemplateRepository
    """
    # TODO: 实现
    # Step 1: 检索候选 POI
    #   pois = await poi_repo.search_by_embedding(query_embedding, top_k=15)
    #   structured_pois = await poi_repo.search_by_filters(
    #       district=intent.constraints.district,
    #       categories=intent.constraints.preferred_cuisines,
    #       max_price=intent.constraints.budget_per_person)
    #   combined = dedupe_and_merge(pois, structured_pois)
    #   candidate_pois = await poi_repo.rank(combined, intent, user_lat, user_lng)
    #   top_30 = candidate_pois[:30]

    # Step 2: LLM 完整生成
    #   route_plan = await llm_client.invoke_structured(
    #       prompt=build_full_generate_prompt(top_30, intent),
    #       output_schema=RoutePlan)

    # Step 3: 异步入库（fire-and-forget）
    #   asyncio.create_task(async_save_as_template(route_plan, intent, query_embedding))

    # Step 4: return RoutePlanResult
    #   return {
    #       "route_result": RoutePlanResult(route=route_plan,
    #           source=FRESH_GENERATED),
    #       "candidate_pois": top_30,
    #   }
    raise NotImplementedError


async def async_save_as_template(route_plan, intent, query_embedding):
    """异步将新路线存入知识库模板表"""
    # TODO: 实现
    # template = RouteTemplate(
    #     scenario=infer_scenario(intent),
    #     district=intent.constraints.district,
    #     typical_duration_min=intent.constraints.time_budget_minutes,
    #     typical_budget=intent.constraints.budget_per_person,
    #     cuisine_tags=intent.constraints.preferred_cuisines,
    #     search_text=intent.raw_query,
    #     query_embedding=query_embedding,
    #     route_json=route_plan.model_dump_json(),
    # )
    # await template_repo.save(template)
    raise NotImplementedError
