"""Auto-relax hard constraints before falling back to degraded routes."""

from __future__ import annotations

from ..state import GraphState, phase_update


def _push_return_by(value: object, minutes: int = 60) -> str | None:
    if not isinstance(value, str) or ":" not in value:
        return None
    hour_text, minute_text = value.split(":", 1)
    if not (hour_text.isdigit() and minute_text.isdigit()):
        return None
    total = int(hour_text) * 60 + int(minute_text) + minutes
    return f"{total // 60:02d}:{total % 60:02d}"


async def auto_relax(state: GraphState) -> dict:
    attempt = int(state.get("relax_attempt", 0))
    constraints = dict(state.get("constraints") or {})
    relaxed: list[str] = []

    if attempt >= 1:
        return phase_update("auto_relax", summary="no relax applied", relax_attempt=attempt)

    budget = constraints.get("budget_per_person")
    if budget is not None:
        constraints["budget_per_person"] = int(round(int(budget) * 1.3))
        relaxed.append("budget_per_person:+30%")

    time_budget = constraints.get("time_budget_minutes")
    if time_budget is not None:
        constraints["time_budget_minutes"] = int(time_budget) + 60
        relaxed.append("time_budget_minutes:+60")

    pushed_return_by = _push_return_by(constraints.get("return_by"))
    if pushed_return_by:
        constraints["return_by"] = pushed_return_by
        relaxed.append("return_by:+60")

    geo_scope = state.get("geo_scope")
    widened_geo_scope = None
    if constraints.get("district") or geo_scope:
        constraints["district"] = "上海市"
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
        geo_scope=widened_geo_scope if widened_geo_scope is not None else state.get("geo_scope"),
        relax_attempt=attempt + 1,
        relaxed_constraints=relaxed,
    )

