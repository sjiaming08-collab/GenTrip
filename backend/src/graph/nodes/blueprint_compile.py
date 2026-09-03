"""Compile LLM activity drafts into POI-searchable feasible blueprints."""

from ...models.blueprint import ItineraryBlueprint
from ...models.constraints import CompiledConstraints, Constraints
from ...services.blueprint_feasibility import compile_blueprint_feasibility
from ..state import GraphState, phase_update


async def blueprint_compile(state: GraphState) -> dict:
    constraints = Constraints.model_validate(state.get("constraints") or {})
    compiled = CompiledConstraints.model_validate(state.get("compiled_constraints") or {})
    blueprints: list[dict] = []
    reports: list[dict] = []
    failures: list[dict] = []
    repair_actions: list[dict] = []
    for raw in state.get("activity_blueprints") or []:
        blueprint, report = compile_blueprint_feasibility(
            ItineraryBlueprint.model_validate(raw), constraints, compiled
        )
        reports.append(report)
        repair_actions.extend(report.get("repair_actions") or [])
        if blueprint is None:
            failures.extend(report.get("conflicts") or [])
        else:
            blueprints.append(blueprint.model_dump(mode="json"))
    active_policies = [dict(item) for item in state.get("active_policies") or []]
    dropped_policies = [dict(item) for item in state.get("dropped_policies") or []]
    surviving_meals = {
        meal
        for meal in ("lunch", "dinner")
        if any(
            slot.get("role") == "meal" and meal in str(slot.get("slot_id"))
            for blueprint in blueprints
            for slot in blueprint.get("slots") or []
        )
    }
    for policy in active_policies:
        policy_id = str(policy.get("policy_id") or "")
        if policy_id in {"meal-lunch", "meal-dinner"}:
            meal = policy_id.removeprefix("meal-")
            policy["status"] = "active" if meal in surviving_meals else "dropped"
            if meal not in surviving_meals:
                dropped_policies.append({
                    "policy_id": policy_id,
                    "reason": "blueprint_temporal_conflict",
                })
    update = phase_update(
        "blueprint_compile",
        summary=f"feasible={len(blueprints)}/{len(reports)} repairs={len(repair_actions)}",
        activity_blueprints=blueprints,
        blueprint_feasibility=reports,
        planning_failures=failures,
        repair_actions=repair_actions,
        active_policies=[item for item in active_policies if item.get("status") != "dropped"],
        dropped_policies=dropped_policies,
    )
    update["phase_log"][0].update({
        "feasible_blueprint_count": len(blueprints),
        "repair_count": len(repair_actions),
        "statuses": [item.get("status") for item in reports],
    })
    return update
