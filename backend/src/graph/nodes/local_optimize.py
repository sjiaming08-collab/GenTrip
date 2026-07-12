"""[Replan 4] local_optimize — 在现有路线骨架上局部替换/插入/删除。"""

from ...models.route import RoutePlan, RouteStop
from ..state import GraphState, phase_update

_VISIT_MINUTES: dict[str, int] = {
    "咖啡": 45, "甜品": 45, "小吃": 30, "快餐": 45,
}


def _travel_estimate(from_stop: dict | None, to_stop: dict) -> int:
    """Simple travel time estimate based on Haversine or default."""
    if from_stop is None:
        return 0
    # Simplified: use fixed estimate between consecutive stops
    return 15  # default 15 min


def _visit_duration(category: str) -> int:
    for key, minutes in _VISIT_MINUTES.items():
        if key in category:
            return minutes
    return 75  # default dining duration


async def local_optimize(state: GraphState) -> dict:
    operation = state.get("replan_operation") or {}
    original = state.get("original_route") or state.get("session_current_route") or {}
    candidates = state.get("replacement_candidates") or []
    locked = set(state.get("locked_stop_indices") or [])
    unlocked = state.get("unlocked_slots") or []
    op_type = operation.get("type", "replace")

    # Stop dictionaries are mutated during renumbering. Copy each one so the
    # original route remains a reliable baseline for render_diff.
    stops: list[dict] = [dict(stop) for stop in original.get("stops", [])]
    if not stops:
        return phase_update("local_optimize")

    if op_type == "delete":
        target = operation.get("target_seq", 1)
        stops = [s for s in stops if s.get("sequence", 0) != target]
        # Renumber sequences
        for i, s in enumerate(stops):
            s["sequence"] = i + 1

    elif op_type == "replace":
        if candidates and unlocked:
            slot = unlocked[0]
            new_poi = candidates[0]
            idx = slot["index"]
            if 0 <= idx < len(stops):
                old_arrival = stops[idx].get("arrival_time", "10:00")
                stops[idx] = {
                    "sequence": stops[idx].get("sequence", idx + 1),
                    "poi_id": new_poi.get("poi_id", ""),
                    "poi_name": new_poi.get("name", ""),
                    "category": new_poi.get("category", ""),
                    "arrival_time": old_arrival,
                    "departure_time": _push_time(old_arrival, _visit_duration(new_poi.get("category", ""))),
                    "visit_duration_min": _visit_duration(new_poi.get("category", "")),
                    "travel_time_from_prev_min": stops[idx].get("travel_time_from_prev_min", 15),
                }

    elif op_type == "add":
        if candidates:
            new_poi = candidates[0]
            after_seq = operation.get("after_seq", len(stops))
            insert_idx = min(after_seq, len(stops))
            prev_stop = stops[insert_idx - 1] if insert_idx > 0 else None
            arrival = "14:00"
            if prev_stop:
                arrival = _push_time(prev_stop.get("departure_time", "13:00"), 15)
            new_stop = {
                "sequence": insert_idx + 1,
                "poi_id": new_poi.get("poi_id", ""),
                "poi_name": new_poi.get("name", ""),
                "category": new_poi.get("category", ""),
                "arrival_time": arrival,
                "departure_time": _push_time(arrival, _visit_duration(new_poi.get("category", ""))),
                "visit_duration_min": _visit_duration(new_poi.get("category", "")),
                "travel_time_from_prev_min": 15,
            }
            stops.insert(insert_idx, new_stop)
            for i, s in enumerate(stops):
                s["sequence"] = i + 1

    # Build updated RoutePlan
    total_dur = sum(s.get("visit_duration_min", 60) + s.get("travel_time_from_prev_min", 15) for s in stops)
    total_cost = sum(75 for _ in stops)  # simplified

    updated = {
        "plan_id": original.get("plan_id", ""),
        "plan_name": original.get("plan_name", "修订路线"),
        "summary": f"修订后 {len(stops)} 站路线",
        "stops": stops,
        "total_duration_min": total_dur,
        "estimated_cost_per_person": total_cost,
    }

    return phase_update(
        "local_optimize",
        summary=f"op={op_type} stops={len(stops)} dur={total_dur}min cost={total_cost}",
        valid_routes=[updated],
        candidate_routes=[updated],
    )


def _push_time(time_str: str, minutes: int) -> str:
    """Push a HH:MM time forward by minutes."""
    parts = time_str.split(":")
    if len(parts) != 2:
        return time_str
    try:
        h, m = int(parts[0]), int(parts[1])
    except ValueError:
        return time_str
    total = h * 60 + m + minutes
    return f"{total // 60 % 24:02d}:{total % 60:02d}"
