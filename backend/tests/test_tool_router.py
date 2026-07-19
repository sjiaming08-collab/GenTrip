import pytest

from src.services.tool_router import ToolRouter


@pytest.mark.asyncio
async def test_fixture_backed_poi_tools_return_real_hours_and_distance():
    router = ToolRouter(max_calls_per_run=3)

    detail = await router.call("poi_detail", {"poi_id": "dp:sh_xh_food_001"})
    hours = await router.call("business_hours", {"poi_id": "sh_xh_food_001", "at_time": "15:00"})
    distance = await router.call("distance", {"from_poi_id": "sh_xh_food_001", "to_poi_id": "sh_xh_food_002"})

    assert detail["rating"] == 4.7
    assert detail["opening_hours"]
    assert hours["known"] is True
    assert hours["is_open"] is False
    assert distance["estimated_minutes"] > 0
    assert distance["source"] == "mock_haversine"


@pytest.mark.asyncio
async def test_fixture_backed_poi_tools_report_missing_poi():
    result = await ToolRouter().call("poi_detail", {"poi_id": "missing"})

    assert result == {"error": "poi_not_found", "poi_id": "missing"}
