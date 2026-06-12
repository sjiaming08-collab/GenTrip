"""输出渲染节点 — 生成结构化响应 + 地图链接 + SSE 推送

职责:
  1. 接收 route_result
  2. 生成高德地图 DeepLink
  3. 推送 SSE 完成事件
  4. 纯逻辑，不调用 LLM
"""

from ..state import GraphState


async def render_output(state: GraphState) -> dict:
    """
    输入: state["route_result"]
    输出: route_result (补充 map_deep_link), current_phase="render_output",
          messages: 推送 SSE 完成事件
    """
    # TODO: 实现
    # 1. 生成高德地图 deep link
    #    - 拼接 stops 的坐标 → amapuri://route/plan?origin=...
    # 2. 可选: 查天气 → weather_note
    # 3. 推送 SSE completion 事件
    # return {
    #     "route_result": enriched_result,
    #     "current_phase": "render_output",
    #     "messages": [{"type": "complete", "route": ...}],
    # }
    raise NotImplementedError
