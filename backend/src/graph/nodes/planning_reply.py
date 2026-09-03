"""Terminal response for a pre-retrieval planning decision."""

from ...models.route import Presentation
from ..state import GraphState, phase_update


async def planning_reply(state: GraphState) -> dict:
    decision = state.get("planning_decision") or {}
    status = str(decision.get("status") or "infeasible")
    reasons = [str(item) for item in decision.get("reasons") or []]
    options = decision.get("options") or []
    missing_required_slots = list(
        (state.get("retrieval_meta") or {}).get("missing_required_slots") or []
    )
    planning_failures = list(state.get("planning_failures") or [])
    if not state.get("valid_routes") and planning_failures:
        status = "infeasible"
        first = planning_failures[0]
        failure_type = str(first.get("failure_type") or "explicit_constraint_conflict")
        slot_id = str(first.get("slot_id") or "")
        labels = {
            "candidate_absent": "必选活动没有可靠地点候选。",
            "provider_unavailable": "地图数据服务暂不可用。",
            "temporal_conflict": "必选活动与可用时间窗口冲突。",
            "opening_conflict": "候选地点在计划时段未营业。",
            "spatial_conflict": "活动地点之间距离超出可执行范围。",
            "budget_conflict": "明确预算不足以覆盖必选活动。",
            "queue_conflict": "候选地点排队时间超过明确上限。",
            "explicit_constraint_conflict": "当前明确约束之间存在冲突。",
        }
        reasons = [f"{labels.get(failure_type, labels['explicit_constraint_conflict'])}{f'（{slot_id}）' if slot_id else ''}"]
        options = []
    if not state.get("valid_routes") and missing_required_slots:
        status = "infeasible"
        reasons = [
            "必选活动未检索到可靠地点，已停止生成，未使用虚构 POI。"
        ]
        options = [
            {"action": "expand_area", "label": "扩大检索范围"},
            {"action": "relax_category", "label": "放宽活动类别"},
            {"action": "remove_slot", "label": "移除该活动"},
        ]
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
