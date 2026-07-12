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


@pytest.mark.asyncio
async def test_session_history_lists_turns_and_persists_title(client):
    session_id = "api-history-001"
    await client.post(
        "/api/v1/routes/plan",
        json={"query": "黄浦区喝咖啡", "session_id": session_id, "user_id": "history-user"},
    )

    listed = await client.get("/api/v1/sessions", params={"user_id": "history-user"})
    assert listed.status_code == 200
    assert listed.json()["sessions"][0]["session_id"] == session_id

    updated = await client.patch(f"/api/v1/sessions/{session_id}", json={"title": "周末咖啡路线"})
    assert updated.status_code == 200
    assert updated.json()["title"] == "周末咖啡路线"
    assert len(updated.json()["turns"]) == 1
    assert updated.json()["latest_response"]["session_id"] == session_id
