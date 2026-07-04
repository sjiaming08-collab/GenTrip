import pytest


@pytest.mark.asyncio
async def test_plan_api_reject_reply_envelope(client):
    response = await client.post(
        "/api/v1/routes/plan",
        json={"query": "今天股票怎么样", "session_id": "api-reject-001"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reply_type"] == "reject"
    assert body["structured"] == []
    assert body["route_results"] == []
    assert body["meta"]["next_suggested_user_moves"]


@pytest.mark.asyncio
async def test_session_api_returns_saved_turn(client):
    session_id = "api-session-001"
    response = await client.post(
        "/api/v1/routes/plan",
        json={"query": "徐汇逛吃", "session_id": session_id},
    )
    assert response.status_code == 200

    session_response = await client.get(f"/api/v1/sessions/{session_id}")
    assert session_response.status_code == 200
    body = session_response.json()
    assert body["session_id"] == session_id
    assert body["turn_count"] == 1
    assert body["recent_turns"][0]["user_query"] == "徐汇逛吃"
