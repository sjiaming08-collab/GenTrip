from src.graph.nodes.route_present import _fallback_presentation
from src.models.route import ScoredRoute


def test_fallback_presentation_includes_retrieved_ugc_summary():
    scored = ScoredRoute.model_validate(
        {
            "route": {
                "plan_id": "plan-1",
                "plan_name": "test plan",
                "summary": "summary",
                "total_duration_min": 90,
                "estimated_cost_per_person": 80,
                "stops": [{
                    "sequence": 1,
                    "poi_id": "poi-1",
                    "poi_name": "POI One",
                    "category": "coffee",
                    "arrival_time": "14:00",
                    "departure_time": "14:45",
                    "visit_duration_min": 45,
                }],
            },
            "execution_score": 0.9,
            "quality_score": 0.9,
            "preference_score": 0.9,
            "final_score": 0.9,
        }
    )

    presentation = _fallback_presentation(
        scored,
        {"candidate_pois": [{"poi_id": "poi-1", "ugc_summary": "quiet seating and reliable coffee"}]},
    )

    assert "POI One: quiet seating and reliable coffee" in presentation.highlights
