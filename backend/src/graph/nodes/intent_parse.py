"""意图解析节点 — NL → RouteIntent

职责:
  1. 接收 user_query
  2. 调用 BaseLLMClient.invoke_structured(RouteIntent)
  3. 回填默认值 (RouteConstraints.with_defaults)
  4. 输出 route_intent
"""

from ..state import GraphState


async def intent_parse(state: GraphState) -> dict:
    """
    输入: state["user_query"], state["user_id"]
    输出: route_intent, current_phase="intent_parse"
    依赖: BaseLLMClient (注入方式待定)
    """
    # TODO: 实现
    # 1. 构建 few-shot prompt
    # 2. llm_client.invoke_structured(prompt, RouteIntent)
    # 3. intent.constraints.with_defaults()
    # 4. return {"route_intent": ..., "current_phase": "intent_parse"}
    raise NotImplementedError
