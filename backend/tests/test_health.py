import pytest


@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["step"] == "local-beta"
    assert body["runtime_stage"] == "P1-runtime-core"
