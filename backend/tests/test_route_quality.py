from tests.golden_conversation_runner import route_quality
from src.graph.nodes.route_evaluate import _rule_scores
from src.models.route import RoutePlan


def test_route_quality_reports_schedule_slack_and_budget_utilization():
    state = {
        "constraints": {"budget_per_person": 100, "start_at": "14:00", "return_by": "18:00"},
        "route_results": [
            {
                "route": {
                    "estimated_cost_per_person": 60,
                    "total_duration_min": 150,
                    "stops": [
                        {
                            "poi_id": "p1",
                            "category": "咖啡",
                            "arrival_time": "14:15",
                            "departure_time": "15:00",
                            "travel_time_from_prev_min": 0,
                            "queue_wait_min": 0,
                        },
                        {
                            "poi_id": "p2",
                            "category": "博物馆",
                            "arrival_time": "15:20",
                            "departure_time": "16:30",
                            "travel_time_from_prev_min": 20,
                            "queue_wait_min": 10,
                        },
                    ],
                }
            }
        ],
        "candidate_pois": [{"poi_id": "p1", "rating": 4.5}, {"poi_id": "p2", "rating": 4.0}],
    }

    quality = route_quality(state)

    assert quality["feasible"] is True
    assert quality["start_slack_min"] == 15
    assert quality["return_slack_min"] == 90
    assert quality["budget_utilization"] == 0.6


def test_rule_preference_coverage_does_not_reward_duplicate_cuisine_stops():
    constraints = {
        "budget_per_person": 150,
        "time_budget_minutes": 240,
        "domains": ["dining", "sightseeing"],
        "preferred_cuisines": ["咖啡"],
    }
    state = {
        "candidate_pois": [
            {"poi_id": "cafe-1", "rating": 4.5, "dimension": "dining"},
            {"poi_id": "cafe-2", "rating": 4.5, "dimension": "dining"},
            {"poi_id": "museum", "rating": 4.5, "dimension": "sightseeing"},
        ]
    }

    def route(stops):
        return RoutePlan.model_validate({
            "plan_name": "测试路线",
            "summary": "测试",
            "stops": stops,
            "total_duration_min": 180,
            "estimated_cost_per_person": 100,
        })

    one_cafe = route([
        {"sequence": 1, "poi_id": "cafe-1", "poi_name": "咖啡 A", "category": "咖啡", "arrival_time": "14:00", "departure_time": "14:45", "visit_duration_min": 45},
        {"sequence": 2, "poi_id": "museum", "poi_name": "博物馆", "category": "博物馆", "arrival_time": "15:00", "departure_time": "16:00", "visit_duration_min": 60},
    ])
    two_cafes = route([
        *one_cafe.model_dump()["stops"],
        {"sequence": 3, "poi_id": "cafe-2", "poi_name": "咖啡 B", "category": "咖啡", "arrival_time": "16:15", "departure_time": "17:00", "visit_duration_min": 45},
    ])

    assert _rule_scores(one_cafe, constraints, state)[2] == _rule_scores(two_cafes, constraints, state)[2]
