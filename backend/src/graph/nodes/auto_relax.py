"""Auto-relax hard constraints before falling back to degraded routes."""

from __future__ import annotations

from ..state import GraphState, phase_update


def _is_assumed(state: GraphState, slot: str) -> bool:
    return any(
        item.get("slot") == slot and item.get("source") not in {"user", "explicit_user"}
        for item in state.get("assumptions") or []
    )


async def auto_relax(state: GraphState) -> dict:
    attempt = int(state.get("relax_attempt", 0))
    constraints = dict(state.get("constraints") or {})
    original_constraints = state.get("original_constraints") or dict(constraints)
    relaxed: list[str] = []

    if attempt >= 1:
        return phase_update("auto_relax", summary="no relax applied", relax_attempt=attempt)

    budget = constraints.get("budget_per_person")
    if budget is not None and _is_assumed(state, "budget_per_person"):
        constraints["budget_per_person"] = int(round(int(budget) * 1.3))
        relaxed.append("budget_per_person:+30%")

    time_budget = constraints.get("time_budget_minutes")
    if time_budget is not None and _is_assumed(state, "time_budget_minutes"):
        constraints["time_budget_minutes"] = int(time_budget) + 60
        relaxed.append("time_budget_minutes:+60")

    geo_scope = state.get("geo_scope")
    widened_geo_scope = None
    if (constraints.get("district") or geo_scope) and _is_assumed(state, "district"):
        widened_geo_scope = {
            "raw_mentions": [],
            "resolved_name": "上海市",
            "scope_type": "city",
            "district": None,
            "business_area": None,
            "center_lat": None,
            "center_lng": None,
            "radius_m": None,
            "confidence": 0.2,
            "source": "auto_relax",
            "assumptions": [],
        }
        relaxed.append("geo_scope:citywide")

    return phase_update(
        "auto_relax",
        summary=",".join(relaxed) if relaxed else "no relax applied",
        constraints=constraints,
        original_constraints=original_constraints,
        geo_scope=widened_geo_scope if widened_geo_scope is not None else state.get("geo_scope"),
        plan_path="cold" if state.get("plan_path") == "hot" else state.get("plan_path"),
        bundle_candidates=[] if state.get("plan_path") == "hot" else state.get("bundle_candidates"),
        matched_bundle_id=None if state.get("plan_path") == "hot" else state.get("matched_bundle_id"),
        relax_attempt=attempt + 1,
        relaxed_constraints=relaxed,
    )

