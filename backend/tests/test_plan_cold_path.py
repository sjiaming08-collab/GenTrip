import pytest


@pytest.mark.asyncio
async def test_cold_path_plan_run(plan_service):
    state = await plan_service.run_plan("徐汇逛吃")
    assert state["run_status"] == "completed"
    assert state["plan_path"] == "cold"
    assert len(state["assumptions"]) >= 1
    assert len(state["route_results"]) >= 1
    assert state["route_results"][0]["route"]["stops"]


@pytest.mark.asyncio
async def test_plan_api(client):
    response = await client.post(
        "/api/v1/routes/plan",
        json={"query": "徐汇逛吃3小时"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["run_status"] == "completed"
    assert body["plan_path"] == "cold"
    assert len(body["route_results"]) >= 1
    assert body["presentation"] is not None
