from src.services.plan_service import PlanService


def test_constraint_extract_event_exposes_safe_structured_constraints():
    event = PlanService._phase_event(
        {
            "current_phase": "constraint_extract",
            "constraints": {
                "district": "黄浦区",
                "domains": ["sightseeing"],
                "budget_per_person": 100,
                "time_budget_minutes": 180,
                "start_at": "14:00",
                "return_by": "18:00",
                "queue_tolerance_minutes": None,
                "poi_count": 3,
                "preferred_cuisines": None,
                "excluded_categories": [],
            },
        },
        {"phase": "constraint_extract", "status": "completed", "summary": "extracted constraints"},
    )

    constraints = event["data"]["extracted_constraints"]
    assert constraints["time_budget_minutes"] == 180
    assert constraints["start_at"] == "14:00"
    assert "queue_tolerance_minutes" not in constraints
