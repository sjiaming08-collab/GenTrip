from src.models.route import RoutePlan
from src.services.route_judge import judge_route


def _route(category: str = "公园") -> RoutePlan:
    return RoutePlan.model_validate({
        "plan_id": "judge-route",
        "plan_name": "测试路线",
        "summary": "测试",
        "total_duration_min": 100,
        "estimated_cost_per_person": 80,
        "stops": [{
            "sequence": 1,
            "poi_id": "poi-1",
            "poi_name": "测试地点",
            "category": category,
            "arrival_time": "14:00",
            "departure_time": "15:40",
            "visit_duration_min": 100,
            "travel_time_from_prev_min": 0,
        }],
    })


def test_route_judge_enforces_excluded_category():
    result = judge_route(_route("美术馆"), {"budget_per_person": 100, "excluded_categories": ["美术馆"]})

    assert result.feasible is False
    assert any("命中排除项" in item for item in result.hard_violations)


def test_route_judge_reports_uncertain_return_time_as_risk():
    route = _route()
    route.stops[0].travel_time_from_prev_min = 10
    route.stops[0].travel_time_lower_bound_min = 8
    route.stops[0].travel_time_upper_bound_min = 35
    result = judge_route(route, {"budget_per_person": 100, "return_by": "16:00"})

    assert result.feasible is True
    assert any("交通波动" in item for item in result.risks)


def test_route_judge_rejects_duplicate_names_with_different_ids():
    route = _route()
    duplicate = route.stops[0].model_copy(deep=True)
    duplicate.sequence = 2
    duplicate.poi_id = "poi-2"
    duplicate.arrival_time = "15:40"
    duplicate.departure_time = "16:40"
    duplicate.travel_time_from_prev_min = 0
    route.stops.append(duplicate)
    route.total_duration_min = 160

    result = judge_route(route, {"budget_per_person": 100})

    assert result.feasible is False
    assert any("重复出现" in item for item in result.hard_violations)
