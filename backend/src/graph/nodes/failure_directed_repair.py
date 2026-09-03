"""Repair only the layer named by a structured planning failure."""

from __future__ import annotations

from copy import deepcopy

from ..state import GraphState, phase_update


def _is_hard_budget(state: GraphState) -> bool:
    return any(
        item.get("field") == "budget_per_person" and item.get("strength") == "hard"
        for item in (state.get("compiled_constraints") or {}).get("atoms") or []
    )


def _remove_lowest_priority_slot(blueprints: list[dict]) -> tuple[list[dict], dict | None]:
    updated = deepcopy(blueprints)
    for level in ("optional", "policy"):
        for blueprint in updated:
            slots = blueprint.get("slots") or []
            index = next(
                (
                    position for position in range(len(slots) - 1, -1, -1)
                    if slots[position].get("requirement_level") == level
                    and slots[position].get("role") != "rest"
                ),
                None,
            )
            if index is not None:
                removed = slots.pop(index)
                return updated, {
                    "action": f"drop_{level}",
                    "slot_id": removed.get("slot_id"),
                    "reason": "route_infeasible",
                }
    return updated, None


async def failure_directed_repair(state: GraphState) -> dict:
    attempt = int(state.get("relax_attempt") or 0)
    if attempt >= 2:
        return phase_update(
            "failure_directed_repair",
            summary="repair budget exhausted",
            repair_applied=False,
            relax_attempt=attempt,
        )

    constraints = deepcopy(state.get("constraints") or {})
    geo_scope = deepcopy(state.get("geo_scope") or {})
    blueprints = deepcopy(state.get("activity_blueprints") or [])
    failures = list(state.get("planning_failures") or [])
    retrieval_missing = list((state.get("retrieval_meta") or {}).get("missing_required_slots") or [])
    actions: list[dict] = []

    if retrieval_missing:
        current_radius = int(geo_scope.get("radius_m") or 2000)
        maximum_radius = 8000 if constraints.get("location_mentions") else 15000
        if current_radius < maximum_radius:
            geo_scope["radius_m"] = min(maximum_radius, max(current_radius + 1000, round(current_radius * 1.5)))
            actions.append({
                "action": "expand_named_area_radius",
                "from_radius_m": current_radius,
                "to_radius_m": geo_scope["radius_m"],
                "slot_ids": retrieval_missing,
            })

    failure_types = {str(item.get("failure_type")) for item in failures}
    if not actions and failure_types & {"temporal_conflict", "opening_conflict", "spatial_conflict"}:
        blueprints, action = _remove_lowest_priority_slot(blueprints)
        if action:
            actions.append(action)

    if not actions and "budget_conflict" in failure_types and not _is_hard_budget(state):
        old_budget = int(constraints.get("budget_per_person") or 0)
        constraints["budget_per_person"] = max(old_budget + 30, round(old_budget * 1.3))
        actions.append({
            "action": "relax_policy_budget",
            "from": old_budget,
            "to": constraints["budget_per_person"],
        })

    if not actions and not state.get("valid_routes"):
        blueprints, action = _remove_lowest_priority_slot(blueprints)
        if action:
            actions.append(action)

    applied = bool(actions)
    update = phase_update(
        "failure_directed_repair",
        summary=(",".join(item["action"] for item in actions) if actions else "no safe repair"),
        repair_applied=applied,
        repair_actions=actions,
        constraints=constraints,
        geo_scope=geo_scope,
        activity_blueprints=blueprints,
        candidate_pois=[],
        candidate_pois_by_slot={},
        candidate_routes=[],
        valid_routes=[],
        relax_attempt=attempt + 1,
    )
    update["phase_log"][0].update({
        "repair_attempt": attempt + 1,
        "repair_actions": actions,
        "protected_named_location": bool(constraints.get("location_mentions")),
    })
    return update
