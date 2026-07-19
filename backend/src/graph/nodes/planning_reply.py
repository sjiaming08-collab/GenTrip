"""Terminal response for a pre-retrieval planning decision."""

from ...models.route import Presentation
from ..state import GraphState, phase_update


async def planning_reply(state: GraphState) -> dict:
    decision = state.get("planning_decision") or {}
    status = str(decision.get("status") or "infeasible")
    reasons = [str(item) for item in decision.get("reasons") or []]
    options = decision.get("options") or []
    if not state.get("valid_routes") and state.get("validation_reports"):
        status = "infeasible"
        reasons = list(dict.fromkeys(
            str(reason)
            for report in state.get("validation_reports") or []
            for reason in report.get("violations") or []
        ))[:3]
        options = [
            {"action": "extend_time", "label": "延长可用时间"},
            {"action": "reduce_activity", "label": "减少一个活动"},
            {"action": "increase_budget", "label": "提高预算"},
        ]
    if status == "clarification_required":
        title, reply_type = "还需要一点信息", "clarification"
        summary = reasons[0] if reasons else "请补充规划地点或可用时间。"
    else:
        title, reply_type = "当前约束下暂不可行", "infeasible"
        summary = reasons[0] if reasons else "当前活动无法在可用时间内完成。"
    presentation = Presentation(
        title=title,
        summary=summary,
        highlights=[str(item.get("label")) for item in options if item.get("label")],
    )
    return phase_update(
        "planning_reply",
        summary=summary,
        route_results=[],
        presentation=presentation.model_dump(mode="json"),
        reply_type=reply_type,
        run_status="completed",
        degraded=False,
        planning_outcome="clarification_required" if status == "clarification_required" else "infeasible",
    )
