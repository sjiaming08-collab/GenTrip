"""Deterministic travel-mode selection and RouteLeg construction."""

from __future__ import annotations

from ..models.route import RouteLeg, ScoredPoi
from .travel_time import TravelEstimate, mock_travel_estimator, travel_time_service


def _estimated_cost(mode: str, distance_m: int) -> int:
    if mode in {"walking", "cycling"}:
        return 0
    if mode == "transit":
        return 3 if distance_m <= 10000 else 6
    return max(15, round(distance_m / 1000 * 3.0))


def _mode_score(
    mode: str,
    estimate: TravelEstimate,
    *,
    budget_per_person: int,
    mobility_preferences: list[str],
) -> float:
    preferences = " ".join(mobility_preferences)
    score = float(estimate.duration_min) + _estimated_cost(mode, estimate.distance_m) * 1.5
    if any(term in preferences for term in ("少走路", "少步行", "不走路", "行动不便")):
        if mode == "walking":
            score += 45
        elif mode == "cycling":
            score += 20
    if mode == "driving" and budget_per_person < 100:
        score += 30
    return score


async def select_route_leg(
    origin: ScoredPoi,
    destination: ScoredPoi,
    *,
    budget_per_person: int,
    mobility_preferences: list[str] | None = None,
) -> RouteLeg:
    """Compare only policy-eligible modes; the LLM never computes distance."""

    preferences = mobility_preferences or []
    base = mock_travel_estimator.estimate(
        origin.lat, origin.lng, destination.lat, destination.lng, mode="walking"
    )
    distance_m = base.distance_m
    if distance_m <= 1200:
        candidate_modes = ["walking"]
    elif distance_m <= 5000:
        candidate_modes = ["walking", "cycling", "transit"]
    else:
        candidate_modes = ["transit", "driving"]

    estimates: dict[str, TravelEstimate] = {}
    for mode in candidate_modes:
        if mode in {"walking", "driving"}:
            estimates[mode] = await travel_time_service.estimate(
                origin.lat,
                origin.lng,
                destination.lat,
                destination.lng,
                mode=mode,
            )
        else:
            estimates[mode] = mock_travel_estimator.estimate(
                origin.lat,
                origin.lng,
                destination.lat,
                destination.lng,
                mode=mode,
            )

    selected_mode = min(
        candidate_modes,
        key=lambda mode: _mode_score(
            mode,
            estimates[mode],
            budget_per_person=budget_per_person,
            mobility_preferences=preferences,
        ),
    )
    selected = estimates[selected_mode]
    reason = (
        "1.2km 内优先步行"
        if candidate_modes == ["walking"]
        else f"在 {','.join(candidate_modes)} 中按耗时、步行偏好和预算选择"
    )
    return RouteLeg(
        from_poi_id=origin.poi_id,
        to_poi_id=destination.poi_id,
        mode=selected_mode,
        distance_m=selected.distance_m,
        duration_min=selected.duration_min,
        cost_per_person=_estimated_cost(selected_mode, selected.distance_m),
        source=selected.source,
        estimated=selected.estimated,
        confidence=selected.confidence if selected.confidence in {"low", "medium", "high"} else "medium",
        fallback_used=selected.fallback_used,
        selection_reason=reason,
    )
