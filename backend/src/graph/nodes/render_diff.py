"""[Replan 6] render_diff — 生成 DiffReply。"""

from difflib import SequenceMatcher

from ...models.diff import DiffEntry, RoutePlanDiff
from ...models.route import Presentation, RoutePlanResult, RouteScores
from ..state import GraphState, phase_update


def _stop_key(stop: dict) -> str:
    """Prefer stable POI identity so insertions/deletions do not shift the diff."""
    poi_id = str(stop.get("poi_id") or "").strip()
    if poi_id:
        return f"poi:{poi_id}"
    return f"name:{str(stop.get('poi_name') or '').strip()}"


def _build_changes(original: list[dict], updated: list[dict], operation: dict) -> list[DiffEntry]:
    changes: list[DiffEntry] = []
    matcher = SequenceMatcher(
        a=[_stop_key(stop) for stop in original],
        b=[_stop_key(stop) for stop in updated],
        autojunk=False,
    )

    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if tag == "equal":
            for old_index, new_index in zip(range(old_start, old_end), range(new_start, new_end)):
                old_name = original[old_index].get("poi_name", "")
                new_name = updated[new_index].get("poi_name", "")
                changes.append(DiffEntry(
                    type="unchanged",
                    sequence=new_index + 1,
                    old_poi_name=old_name,
                    new_poi_name=new_name,
                ))
            continue

        if tag == "delete":
            for old_index in range(old_start, old_end):
                changes.append(DiffEntry(
                    type="removed",
                    sequence=old_index + 1,
                    old_poi_name=original[old_index].get("poi_name", ""),
                ))
            continue

        if tag == "insert":
            for new_index in range(new_start, new_end):
                changes.append(DiffEntry(
                    type="added",
                    sequence=new_index + 1,
                    new_poi_name=updated[new_index].get("poi_name", ""),
                ))
            continue

        # A replace opcode can contain unequal counts. Pair the overlapping
        # positions as replacements, then report the remaining insertions or deletions.
        pair_count = min(old_end - old_start, new_end - new_start)
        for offset in range(pair_count):
            old_index = old_start + offset
            new_index = new_start + offset
            changes.append(DiffEntry(
                type="replaced",
                sequence=new_index + 1,
                old_poi_name=original[old_index].get("poi_name", ""),
                new_poi_name=updated[new_index].get("poi_name", ""),
                reason=f"用户要求{operation.get('type', '修订')}",
            ))
        for old_index in range(old_start + pair_count, old_end):
            changes.append(DiffEntry(
                type="removed",
                sequence=old_index + 1,
                old_poi_name=original[old_index].get("poi_name", ""),
            ))
        for new_index in range(new_start + pair_count, new_end):
            changes.append(DiffEntry(
                type="added",
                sequence=new_index + 1,
                new_poi_name=updated[new_index].get("poi_name", ""),
            ))

    return changes


async def render_diff(state: GraphState) -> dict:
    original = state.get("original_route") or {}
    delta_valid = bool(state.get("delta_valid", True))
    updated_routes = state.get("valid_routes") or (state.get("candidate_routes") or [] if delta_valid else [])
    operation = state.get("replan_operation") or {}

    if not delta_valid:
        violations = (state.get("validation_reports") or [{}])[0].get("violations") or []
        route_plan = original
        diff = RoutePlanDiff(
            original_plan_id=original.get("plan_id", ""),
            new_plan_id=original.get("plan_id", ""),
            changes=_build_changes(original.get("stops", []), original.get("stops", []), operation),
            summary="无法在当前时间和预算约束内完成本次调整，已保留原路线",
        )
        presentation = Presentation(
            title="路线暂未调整",
            summary=diff.summary,
            highlights=[str(item) for item in violations[:3]],
        )
        result = RoutePlanResult(
            route=route_plan,
            source="DEGRADED",
            rank=1,
            scores=RouteScores(execution=0.0, quality=0.0, final=0.0),
        )
        return phase_update(
            "render_diff",
            summary=diff.summary,
            diff_result=diff.model_dump(mode="json"),
            route_results=[result.model_dump(mode="json")],
            presentation=presentation.model_dump(mode="json"),
            reply_type="degraded_route",
            degraded=True,
            planning_outcome="change_rejected",
            pending_change=state.get("pending_change") or {
                "operations": state.get("replan_operations") or [operation],
                "status": "not_applied",
                "reasons": [str(item) for item in violations[:5]],
            },
            rejected_change=state.get("pending_change"),
            run_status="completed",
        )

    if not updated_routes:
        return phase_update("render_diff", status="failed", summary="no updated route", run_status="failed", error="no_updated_route")

    updated = updated_routes[0]
    orig_stops = original.get("stops", [])
    new_stops = updated.get("stops", [])

    changes = _build_changes(orig_stops, new_stops, operation)

    # Generate summary
    summary_parts = []
    for c in changes:
        if c.type == "replaced":
            summary_parts.append(f"第{c.sequence}站从{c.old_poi_name}替换为{c.new_poi_name}")
        elif c.type == "removed":
            summary_parts.append(f"去掉了第{c.sequence}站{c.old_poi_name}")
        elif c.type == "added":
            summary_parts.append(f"新增了第{c.sequence}站{c.new_poi_name}")

    diff = RoutePlanDiff(
        original_plan_id=original.get("plan_id", ""),
        new_plan_id=updated.get("plan_id", ""),
        changes=changes,
        summary="；".join(summary_parts) if summary_parts else "路线已更新",
    )

    # Build presentation
    presentation = Presentation(
        title="路线修订",
        summary=diff.summary,
        highlights=[f"{c.type}: {c.old_poi_name} → {c.new_poi_name}" for c in changes if c.type in ("replaced", "added", "removed")],
    )

    # Build route result
    route_plan = updated if isinstance(updated, dict) else updated
    result = RoutePlanResult(
        route=route_plan,
        source="DEGRADED" if state.get("degraded") else "COLD_GENERATED",
        rank=1,
        scores=RouteScores(execution=0.8, quality=0.8, final=0.8),
    )

    return phase_update(
        "render_diff",
        summary=diff.summary,
        diff_result=diff.model_dump(mode="json"),
        route_results=[result.model_dump(mode="json")],
        presentation=presentation.model_dump(mode="json"),
        reply_type="diff",
        planning_outcome="change_applied",
        pending_change=None,
        run_status="completed",
    )
