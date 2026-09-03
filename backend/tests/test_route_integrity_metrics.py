from src.evaluation.route_integrity import route_integrity_metrics


def test_integrity_metrics_gate_legs_provider_ids_meals_and_anchor_count():
    route = {
        "plan_id": "route-1",
        "blueprint_id": "bp-balanced",
        "stops": [
            {
                "poi_id": "provider:a",
                "slot_role": "anchor",
                "arrival_time": "10:00",
                "departure_time": "11:00",
            },
            {
                "poi_id": "provider:meal",
                "slot_role": "meal",
                "slot_time_window": {"start": "11:30", "end": "13:30"},
                "arrival_time": "12:00",
                "departure_time": "13:00",
            },
        ],
        "legs": [
            {
                "from_poi_id": "provider:a",
                "to_poi_id": "provider:meal",
                "mode": "walking",
                "source": "amap_walking",
                "confidence": "high",
            }
        ],
    }
    state = {
        "constraints": {"anchor_count_explicit": 1},
        "candidate_pois": [{"poi_id": "provider:a"}, {"poi_id": "provider:meal"}],
        "validation_reports": [{"route_id": "route-1", "violations": []}],
    }

    metrics = route_integrity_metrics(state, route)

    assert metrics == {
        "route_leg_complete": True,
        "fabricated_poi_count": 0,
        "meal_window_satisfaction_rate": 1.0,
        "explicit_anchor_satisfied": True,
        "hard_constraint_violation_count": 0,
    }


def test_integrity_metrics_detect_fabrication_and_incomplete_leg():
    route = {
        "plan_id": "route-2",
        "blueprint_id": "bp-balanced",
        "stops": [{"poi_id": "invented", "slot_role": "anchor"}],
        "legs": [{"from_poi_id": "x", "to_poi_id": "y"}],
    }
    state = {
        "constraints": {"anchor_count_explicit": 2},
        "candidate_pois": [{"poi_id": "provider:a"}],
    }

    metrics = route_integrity_metrics(state, route)

    assert metrics["route_leg_complete"] is False
    assert metrics["fabricated_poi_count"] == 1
    assert metrics["explicit_anchor_satisfied"] is False
