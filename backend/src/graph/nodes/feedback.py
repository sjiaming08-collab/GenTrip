"""反馈收集节点 — 用户反馈 → 知识库更新

职责:
  1. 接收用户反馈 (RouteFeedback)
  2. 调用 BaseTemplateRepository.update_after_feedback()
  3. EMA 更新模板评分，低分淘汰

可同步或异步触发。
"""

from ..state import GraphState


async def process_feedback(state: GraphState) -> dict:
    """
    输入: state["feedback"], state["route_result"]
    输出: feedback_processed=True, current_phase="feedback"
    依赖: BaseTemplateRepository

    如果 feedback 为空（用户未提交反馈），直接 pass。
    """
    # TODO: 实现
    # if feedback is None:
    #     return {"feedback_processed": True}

    # template_id = route_result.matched_template_id
    # if template_id:
    #     await template_repo.update_after_feedback(template_id, feedback)

    # return {"feedback_processed": True, "current_phase": "feedback"}
    raise NotImplementedError
