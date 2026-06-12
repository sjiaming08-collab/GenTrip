"""模板适配节点 (轻量 LLM) — matchScore ≥ 0.75 时执行

职责:
  1. 取 best_template 的 route_json
  2. LLM 最小化修改: 替换歇业 POI / 微调时间
  3. 不改变路线骨架

延迟目标: ~800ms, Token: ~500
"""

from ..state import GraphState


async def adapt_template(state: GraphState) -> dict:
    """
    输入: state["best_template"], state["route_intent"]
    输出: route_result (source=CACHE_ADAPTED), current_phase="adapt_template"
    依赖: BaseLLMClient, BasePoiRepository (查换可用的替代 POI)
    """
    # TODO: 实现
    # 1. 从 best_template.route_json 反序列化 RoutePlan
    # 2. 校验每个 stop 的 POI 是否仍营业
    # 3. 如有歇业 POI → llm_client.invoke_structured(
    #        prompt="以下是一个已规划的路线模板，用户需求略有不同。
    #               请保持整体结构和POI顺序，仅做最小修改：
    #               1. 第三站的XX已歇业，请替换为同类同价位POI
    #               2. 根据用户预算微调驻留时间。
    #               不要改变路线骨架。",
    #        output_schema=RoutePlan)
    # 4. return {"route_result": RoutePlanResult(
    #        route=adapted, source=CACHE_ADAPTED,
    #        matched_template_id=best_template.id)}
    raise NotImplementedError
