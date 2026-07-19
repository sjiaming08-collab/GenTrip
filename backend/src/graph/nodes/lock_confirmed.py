"""[Replan 2] lock_confirmed — 锁定未被修订的 stops。"""

from ..state import GraphState, phase_update


async def lock_confirmed(state: GraphState) -> dict:
    operation = state.get("replan_operation") or {}
    operations = state.get("replan_operations") or ([operation] if operation else [])
    current_route = state.get("original_route") or state.get("session_current_route") or {}
    stops = current_route.get("stops", [])
    op_type = operation.get("type", "replace")

    locked_indices: list[int] = []
    unlocked_slots: list[dict] = []

    mutable_indices: set[int] = set()
    for op_index, item in enumerate(operations):
        item_type = item.get("type", "replace")
        if item_type == "replace":
            target = item.get("target_seq", 1)
            for i, stop in enumerate(stops):
                seq = stop.get("sequence", i + 1)
                if seq == target:
                    mutable_indices.add(i)
                    unlocked_slots.append({
                        "index": i,
                        "sequence": seq,
                        "operation_index": op_index,
                        "old_poi_name": stop.get("poi_name", ""),
                        "old_category": stop.get("category", ""),
                        "new_cuisine": item.get("new_cuisine"),
                        "new_district": item.get("new_district"),
                        "arrival_time": stop.get("arrival_time"),
                    })
        elif item_type == "add":
            unlocked_slots.append({
                "index": len(stops),
                "sequence": len(stops) + 1,
                "operation_index": op_index,
                "after_seq": item.get("after_seq", len(stops)),
                "new_cuisine": item.get("new_cuisine"),
            })
        # delete/change_pref do not need a retrieval slot.

    locked_indices = [i for i in range(len(stops)) if i not in mutable_indices]
    confirmed_ids = {
        str(item) for item in (state.get("memory_context") or {}).get("confirmed_stop_ids") or []
    }
    explicitly_locked = [
        index for index, stop in enumerate(stops)
        if str(stop.get("poi_id") or "") in confirmed_ids
    ]

    return phase_update(
        "lock_confirmed",
        summary=f"locked={len(locked_indices)} unlocked={len(unlocked_slots)} op={op_type}",
        locked_stop_indices=locked_indices,
        explicitly_locked_stop_indices=explicitly_locked,
        unlocked_slots=unlocked_slots,
    )
