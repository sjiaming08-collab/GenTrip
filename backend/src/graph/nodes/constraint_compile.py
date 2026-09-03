"""Compile extracted facts into hard, soft, and conditional policy constraints."""

from ...models.constraints import Constraints
from ...services.constraint_compiler import compile_constraints
from ..state import GraphState, phase_update


async def constraint_compile(state: GraphState) -> dict:
    constraints = Constraints.model_validate(state.get("constraints") or {})
    normalized, compiled = compile_constraints(constraints)
    hard_count = sum(item.strength == "hard" for item in compiled.atoms)
    soft_count = sum(item.strength == "soft" for item in compiled.atoms)
    policy_count = sum(item.strength == "policy" for item in compiled.atoms)
    compiled_assumptions: list[dict] = []
    if compiled.schedule_envelope.time_scope == "full_day":
        compiled_assumptions.extend([
            {
                "slot": "time_budget_minutes",
                "assumed_value": "420-600",
                "source": "full_day_policy",
                "message": "全天采用7至10小时弹性安排",
                "overridable": True,
            },
            {
                "slot": "poi_count",
                "assumed_value": str(normalized.poi_count_target or 4),
                "source": "activity_density_policy",
                "message": f"全天推荐{normalized.poi_count_target or 4}个主要活动",
                "overridable": True,
            },
        ])
    update = phase_update(
        "constraint_compile",
        summary=(
            f"hard={hard_count} soft={soft_count} policy={policy_count} "
            f"time={compiled.schedule_envelope.time_scope}"
        ),
        constraints=normalized.model_dump(mode="json"),
        compiled_constraints=compiled.model_dump(mode="json"),
        active_policies=compiled.active_policies,
        dropped_policies=compiled.dropped_policies,
        assumptions=compiled_assumptions,
    )
    update["phase_log"][0].update({
        "hard_constraint_count": hard_count,
        "soft_constraint_count": soft_count,
        "policy_constraint_count": policy_count,
        "time_scope": compiled.schedule_envelope.time_scope,
    })
    return update
