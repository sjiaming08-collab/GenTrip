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

    assert update["degraded"] is False
    assert update["valid_routes"] == []
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
    assert update["degraded"] is False
    assert any("总时长" in item for item in violations)
    assert any("晚于返回时间" in item for item in violations)


@pytest.mark.asyncio
async def test_route_validate_checks_start_time_and_queue_tolerance():
    route = _route("too_early")
    route["stops"][0]["queue_wait_min"] = 35
    update = await route_validate(_state([route], start_at="14:00", queue_tolerance_minutes=30))

    violations = update["validation_reports"][0]["violations"]
    assert any("早于出发时间" in item for item in violations)
    assert any("预计排队" in item for item in violations)


@pytest.mark.asyncio
async def test_route_validate_checks_travel_time_legality():
    update = await route_validate(_state([_route("bad_travel", travel=120)]))

    assert update["validation_reports"][0]["feasible"] is False
    assert any("交通时间" in item for item in update["validation_reports"][0]["violations"])


@pytest.mark.asyncio
async def test_route_validate_rejects_stop_outside_opening_hours():
    state = _state([_route("closed")])
    state["candidate_pois"] = [
        {"poi_id": "poi_1", "opening_hours": [{"open": "12:00", "close": "22:00"}]},
        {"poi_id": "poi_2", "opening_hours": [{"open": "10:00", "close": "22:00"}]},
    ]

    update = await route_validate(state)

    violations = update["validation_reports"][0]["violations"]
    assert update["validation_reports"][0]["feasible"] is False
    assert any("在 10:00-11:00 未营业" in item for item in violations)


@pytest.mark.asyncio
async def test_route_validate_respects_weekday_specific_opening_hours():
    state = _state([_route("weekend_closed")])
    state["input_ts"] = "2026-07-18T09:00:00+08:00"  # Saturday
    state["candidate_pois"] = [
        {"poi_id": "poi_1", "opening_hours": [{"days": "Mon-Fri", "open": "09:00", "close": "18:00"}]},
        {"poi_id": "poi_2", "opening_hours": [{"days": "Mon-Sun", "open": "09:00", "close": "18:00"}]},
    ]

    update = await route_validate(state)

    assert update["validation_reports"][0]["feasible"] is False
    assert any("POI 1 在 10:00-11:00 未营业" in item for item in update["validation_reports"][0]["violations"])


@pytest.mark.asyncio
async def test_route_validate_never_promotes_a_violating_route():
    update = await route_validate(
        _state(
            [
                _route("worse", cost=160, duration=260, end="21:00"),
                _route("less_bad", cost=120, duration=170, end="12:00"),
            ],
            return_by="19:00",
        )
    )

    assert update["degraded"] is False
    assert update["valid_routes"] == []
    assert update["relaxed_constraints"] == []
    by_route = {report["route_id"]: report for report in update["validation_reports"]}
    assert by_route["less_bad"]["feasible"] is False
    assert by_route["less_bad"]["violations"]
