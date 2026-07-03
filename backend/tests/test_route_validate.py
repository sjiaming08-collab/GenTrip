import pytest

from src.graph.nodes.route_validate import route_validate


def _stop(sequence: int, *, arrival: str, departure: str, travel: int = 0):
    return {
        "sequence": sequence,
        "poi_id": f"poi_{sequence}",
        "poi_name": f"POI {sequence}",
        "category": "本帮菜",
        "arrival_time": arrival,
        "departure_time": departure,
        "visit_duration_min": 60,
        "travel_time_from_prev_min": travel,
    }


def _route(plan_id: str, *, cost: int = 80, duration: int = 120, end: str = "12:00", travel: int = 8):
    return {
        "plan_id": plan_id,
        "plan_name": plan_id,
        "summary": "test route",
        "stops": [
            _stop(1, arrival="10:00", departure="11:00"),
            _stop(2, arrival="11:08", departure=end, travel=travel),
        ],
        "total_duration_min": duration,
        "estimated_cost_per_person": cost,
    }


def _state(routes: list[dict], **constraint_overrides):
    constraints = {
        "budget_per_person": 100,
        "time_budget_minutes": 180,
    }
    constraints.update(constraint_overrides)
    return {
        "constraints": constraints,
        "candidate_routes": routes,
    }


@pytest.mark.asyncio
async def test_route_validate_accepts_feasible_route():
    update = await route_validate(_state([_route("ok")]))

    assert update["valid_routes"][0]["plan_id"] == "ok"
    assert update["validation_reports"][0]["feasible"] is True
    assert update["degraded"] is False


@pytest.mark.asyncio
async def test_route_validate_rejects_over_budget_route():
    update = await route_validate(_state([_route("expensive", cost=140)]))

    assert update["degraded"] is True
    assert update["valid_routes"][0]["plan_id"] == "expensive"
    assert update["validation_reports"][0]["feasible"] is False
    assert any("超过预算" in item for item in update["validation_reports"][0]["violations"])


@pytest.mark.asyncio
async def test_route_validate_checks_total_duration_and_return_by():
    update = await route_validate(
        _state(
            [_route("late", duration=220, end="20:10")],
            time_budget_minutes=180,
            return_by="19:00",
        )
    )

    violations = update["validation_reports"][0]["violations"]
    assert update["degraded"] is True
    assert any("总时长" in item for item in violations)
    assert any("晚于返回时间" in item for item in violations)


@pytest.mark.asyncio
async def test_route_validate_checks_travel_time_legality():
    update = await route_validate(_state([_route("bad_travel", travel=120)]))

    assert update["validation_reports"][0]["feasible"] is False
    assert any("交通时间" in item for item in update["validation_reports"][0]["violations"])


@pytest.mark.asyncio
async def test_route_validate_degrades_to_least_violating_route_without_rewriting_report():
    update = await route_validate(
        _state(
            [
                _route("worse", cost=160, duration=260, end="21:00"),
                _route("less_bad", cost=120, duration=170, end="12:00"),
            ],
            return_by="19:00",
        )
    )

    assert update["degraded"] is True
    assert update["valid_routes"][0]["plan_id"] == "less_bad"
    assert "route_validate_degraded_best_effort" in update["relaxed_constraints"]
    by_route = {report["route_id"]: report for report in update["validation_reports"]}
    assert by_route["less_bad"]["feasible"] is False
    assert by_route["less_bad"]["violations"]