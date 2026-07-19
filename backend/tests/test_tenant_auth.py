import pytest

from src.config import settings


@pytest.mark.asyncio
async def test_configured_api_key_derives_tenant_and_ignores_request_tenant(client, monkeypatch):
    monkeypatch.setattr(settings, "tenant_api_keys_json", '{"key-for-a":"tenant-a","key-for-b":"tenant-b"}')
    session_id = "00000000-0000-0000-0000-000000000071"

    created = await client.post(
        "/api/v1/routes/plan",
        headers={"X-API-Key": "key-for-a"},
        json={"query": "徐汇区喝咖啡，预算100元", "session_id": session_id, "tenant_id": "tenant-b"},
    )
    own_session = await client.get(f"/api/v1/sessions/{session_id}", headers={"X-API-Key": "key-for-a"})
    foreign_session = await client.get(f"/api/v1/sessions/{session_id}", headers={"X-API-Key": "key-for-b"})

    assert created.status_code == 200
    assert own_session.status_code == 200
    assert own_session.json()["tenant_id"] == "tenant-a"
    assert foreign_session.status_code == 404


@pytest.mark.asyncio
async def test_configured_api_key_rejects_missing_or_unknown_key(client, monkeypatch):
    monkeypatch.setattr(settings, "tenant_api_keys_json", '{"valid-key":"tenant-a"}')

    missing = await client.post("/api/v1/routes/plan", json={"query": "徐汇区喝咖啡"})
    unknown = await client.post(
        "/api/v1/routes/plan",
        headers={"X-API-Key": "unknown"},
        json={"query": "徐汇区喝咖啡"},
    )

    assert missing.status_code == 401
    assert unknown.status_code == 401
