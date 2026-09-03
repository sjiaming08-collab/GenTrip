"""[Replan 4] Generate bounded transactional route proposals."""

from __future__ import annotations

from uuid import uuid4

from ...services.travel_time import mock_travel_estimator
from ..state import GraphState, phase_update

_VISIT_MINUTES: dict[str, int] = {
    "咖啡": 45,
    "甜品": 45,
    "小吃": 30,
    "快餐": 45,
    "日料": 75,
    "火锅": 90,
}
MAX_REPLAN_PROPOSALS = 8


def _visit_duration(category: str) -> int:
    for key, minutes in _VISIT_MINUTES.items():
        if key in category:
            return minutes
    return 75


def _push_time(time_str: str, minutes: int) -> str:
    parts = time_str.split(":")
    if len(parts) != 2:
        return time_str
    try:
        total = int(parts[0]) * 60 + int(parts[1]) + minutes
    except ValueError:
        return time_str
    return f"{total // 60 % 24:02d}:{total % 60:02d}"


def _candidate_stop(candidate: dict) -> dict:
    category = str(candidate.get("category") or "餐饮")
    return {
        "sequence": 0,
        "poi_id": str(candidate.get("poi_id") or ""),
        "poi_name": str(candidate.get("name") or ""),
        "category": category,
        "arrival_time": "00:00",
        "departure_time": "00:00",
        "visit_duration_min": _visit_duration(category),
        "travel_time_from_prev_min": 0,
        "travel_source": "mock_haversine",
        "travel_estimated": True,
        "travel_time_lower_bound_min": 0,
        "travel_time_upper_bound_min": 0,
        "travel_confidence": "medium",
        "queue_wait_min": int(candidate.get("queue_wait_min") or 0),
        "lat": candidate.get("lat"),
        "lng": candidate.get("lng"),
        "slot_id": candidate.get("slot_id"),
        "slot_role": candidate.get("slot_role"),
        "slot_source": candidate.get("slot_source"),
        "slot_time_window": candidate.get("slot_time_window"),
    }


def _travel(prev: dict | None, current: dict) -> tuple[int, int, int, str]:
    if prev is None:
        return 0, 0, 0, "origin"
    coords = (prev.get("lat"), prev.get("lng"), current.get("lat"), current.get("lng"))
    if all(value is not None for value in coords):
        estimate = mock_travel_estimator.estimate(*[float(value) for value in coords], mode="walking")
        return estimate.duration_min, estimate.min_duration_min, estimate.max_duration_min, estimate.source
    expected = int(current.get("travel_time_from_prev_min") or 15)
    return expected, max(1, round(expected * 0.75)), max(expected, round(expected * 1.4)), "local_fallback"


def _reschedule(stops: list[dict], start_at: str) -> list[dict]:
    result: list[dict] = []
    cursor = start_at
    previous: dict | None = None
    for index, raw in enumerate(stops):
        stop = dict(raw)
        travel, lower, upper, source = _travel(previous, stop)
        arrival = _push_time(cursor, travel) if previous is not None else start_at
        queue = int(stop.get("queue_wait_min") or 0)
        visit = int(stop.get("visit_duration_min") or _visit_duration(str(stop.get("category") or "")))
        departure = _push_time(arrival, queue + visit)
        stop.update({
            "sequence": index + 1,
            "arrival_time": arrival,
            "departure_time": departure,
            "visit_duration_min": visit,
            "travel_time_from_prev_min": travel,
            "travel_time_lower_bound_min": lower,
            "travel_time_upper_bound_min": upper,
            "travel_source": source,
            "travel_estimated": source != "origin",
            "travel_confidence": "medium" if source != "origin" else "high",
        })
        result.append(stop)
        cursor = departure
        previous = stop
    return result


def _route_cost(stops: list[dict], original_cost: int, candidates: list[dict]) -> int:
    candidate_prices = {
        str(item.get("poi_id")): int(item.get("price_per_person") or 0)
        for item in candidates
        if item.get("poi_id")
    }
    prices = [candidate_prices.get(str(stop.get("poi_id")), original_cost) for stop in stops]
    return int(sum(prices) / len(prices)) if prices else 0


def _build_route(original: dict, stops: list[dict], strategy: str, candidates: list[dict]) -> dict:
    start_at = str((original.get("stops") or [{}])[0].get("arrival_time") or "10:00")
    scheduled = _reschedule(stops, start_at)
    total_duration = sum(
        int(stop.get("travel_time_from_prev_min") or 0)
        + int(stop.get("queue_wait_min") or 0)
        + int(stop.get("visit_duration_min") or 0)
        for stop in scheduled
    )
    return {
        "plan_id": f"{original.get('plan_id') or uuid4()}-{strategy}",
        "plan_name": original.get("plan_name", "修订路线"),
        "summary": f"{strategy} · 修订后 {len(scheduled)} 站路线",
        "stops": scheduled,
        "total_duration_min": total_duration,
        "estimated_cost_per_person": _route_cost(
            scheduled,
            int(original.get("estimated_cost_per_person") or 0),
            candidates,
        ),
    }


def _operation_candidates(candidates: list[dict], operation_index: int, operation_count: int) -> list[dict]:
    scoped = [item for item in candidates if int(item.get("_replan_operation_index", 0)) == operation_index]
    return (scoped or candidates if operation_count == 1 else scoped)[:6]


def _direct_candidate_variants(operations: list[dict], candidates: list[dict]) -> list[tuple[str, list[dict]]]:
    variants: list[tuple[str, list[dict]]] = [("direct_1", candidates)]
    operation_count = len(operations)
    for operation_index, operation in enumerate(operations):
        if operation.get("type") not in {"add", "replace"}:
            continue
        scoped = _operation_candidates(candidates, operation_index, operation_count)
        for candidate_index, candidate in enumerate(scoped[1:], start=2):
            reordered = [candidate, *(item for item in candidates if item is not candidate)]
            variants.append((f"direct_op_{operation_index + 1}_candidate_{candidate_index}", reordered))
    return variants


def _apply_operations(base: list[dict], operations: list[dict], candidates: list[dict]) -> list[dict]:
    stops = [dict(stop) for stop in base]
    for operation_index, operation in enumerate(operations):
        op_type = operation.get("type", "replace")
        scoped = _operation_candidates(candidates, operation_index, len(operations))
        candidate = scoped[0] if scoped else None
        if op_type == "delete":
            target_slot_id = str(operation.get("target_slot_id") or "")
            category = str(operation.get("target_category") or "")
            if target_slot_id:
                stops = [
                    stop for stop in stops
                    if str(stop.get("slot_id") or "") != target_slot_id
                ]
            elif category:
                stops = [
                    stop for stop in stops
                    if category not in str(stop.get("category") or "")
                    and category not in str(stop.get("poi_name") or "")
                ]
            else:
                target = int(operation.get("target_seq") or 1)
                stops = [stop for index, stop in enumerate(stops, start=1) if index != target]
        elif op_type == "replace" and candidate:
            target = max(0, int(operation.get("target_seq") or 1) - 1)
            if target < len(stops):
                stops[target] = _candidate_stop(candidate)
        elif op_type == "add" and candidate:
            insert_at = min(max(int(operation.get("after_seq") or len(stops)), 0), len(stops))
            stops.insert(insert_at, _candidate_stop(candidate))
    return stops


def _removable_indices(stops: list[dict], explicitly_locked: set[int]) -> list[int]:
    candidates = [index for index in range(len(stops)) if index not in explicitly_locked]
    return sorted(candidates, key=lambda index: ("餐" in str(stops[index].get("category")), -index))


async def local_optimize(state: GraphState) -> dict:
    operation = state.get("replan_operation") or {}
    operations = state.get("replan_operations") or ([operation] if operation else [])
    original = state.get("original_route") or state.get("session_current_route") or {}
    base = [dict(stop) for stop in original.get("stops", [])]
    candidates = state.get("replacement_candidates") or []
    if not base:
        return phase_update("local_optimize", summary="no original route", candidate_routes=[], valid_routes=[])

    proposals: list[tuple[str, list[dict]]] = []
    for strategy, variant_candidates in _direct_candidate_variants(operations, candidates):
        direct = _apply_operations(base, operations, variant_candidates)
        proposals.append((strategy, direct))

    if len(operations) == 1 and operation.get("type") == "add" and candidates:
        locked = set(state.get("explicitly_locked_stop_indices") or [])
        removable = _removable_indices(base, locked)
        for candidate_index, candidate in enumerate(candidates[:3]):
            for index in removable[:2]:
                replacement = [dict(stop) for stop in base]
                replacement[index] = _candidate_stop(candidate)
                proposals.append((f"replace_stop_{index + 1}_candidate_{candidate_index + 1}", replacement))

                remove_and_add = [dict(stop) for stop_index, stop in enumerate(base) if stop_index != index]
                remove_and_add.append(_candidate_stop(candidate))
                proposals.append((f"remove_{index + 1}_and_add_candidate_{candidate_index + 1}", remove_and_add))

    unique: set[tuple[str, ...]] = set()
    routes: list[dict] = []
    proposal_meta: list[dict] = []
    for strategy, stops in proposals:
        key = tuple(str(stop.get("poi_id") or stop.get("poi_name") or "") for stop in stops)
        if key in unique:
            continue
        unique.add(key)
        route = _build_route(original, stops, strategy, candidates)
        routes.append(route)
        proposal_meta.append({
            "proposal_id": route["plan_id"],
            "strategy": strategy,
            "stop_count": len(stops),
            "status": "proposed",
        })
        if len(routes) >= MAX_REPLAN_PROPOSALS:
            break

    return phase_update(
        "local_optimize",
        summary=f"op={operation.get('type', 'replace')} proposals={len(routes)}",
        replan_proposals=proposal_meta,
        candidate_routes=routes,
        valid_routes=routes,
    )
