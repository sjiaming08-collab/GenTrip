"""[Replan 2] lock_confirmed — 锁定未被修订的 stops。"""

from ..state import GraphState, phase_update


async def lock_confirmed(state: GraphState) -> dict:
    operation = state.get("replan_operation") or {}
    current_route = state.get("original_route") or state.get("session_current_route") or {}
    stops = current_route.get("stops", [])
    op_type = operation.get("type", "replace")

    locked_indices: list[int] = []
    unlocked_slots: list[dict] = []

    if op_type == "delete":
        target = operation.get("target_seq", 1)
        for i, stop in enumerate(stops):
            seq = stop.get("sequence", i + 1)
            if seq != target:
                locked_indices.append(i)
        # deleted stop creates no unlocked slot
    elif op_type == "replace":
        target = operation.get("target_seq", 1)
        for i, stop in enumerate(stops):
            seq = stop.get("sequence", i + 1)
            if seq == target:
                unlocked_slots.append({
                    "index": i,
                    "sequence": seq,
                    "old_poi_name": stop.get("poi_name", ""),
                    "old_category": stop.get("category", ""),
                    "new_cuisine": operation.get("new_cuisine"),
                    "new_district": operation.get("new_district"),
                    "arrival_time": stop.get("arrival_time"),
                })
            else:
                locked_indices.append(i)
    elif op_type == "add":
        for i, _stop in enumerate(stops):
            locked_indices.append(i)
        unlocked_slots.append({
            "index": len(stops),
            "sequence": len(stops) + 1,
            "after_seq": operation.get("after_seq", len(stops)),
            "new_cuisine": operation.get("new_cuisine"),
        })
    elif op_type == "change_pref":
        # All stops locked, just constraint override
        for i, _stop in enumerate(stops):
            locked_indices.append(i)

    return phase_update(
        "lock_confirmed",
        summary=f"locked={len(locked_indices)} unlocked={len(unlocked_slots)} op={op_type}",
        locked_stop_indices=locked_indices,
        unlocked_slots=unlocked_slots,
    )
