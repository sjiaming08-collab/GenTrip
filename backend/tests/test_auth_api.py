import pytest

from src.config import settings


def _enable_auth(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-auth-secret-that-is-long-enough-for-hs256")
    monkeypatch.setattr(settings, "tenant_api_keys_json", "")
    monkeypatch.setattr(settings, "allow_insecure_tenant_id", False)


@pytest.mark.asyncio
async def test_auth_required_registers_and_derives_tenant_and_user(client, monkeypatch):
    _enable_auth(monkeypatch)

    anonymous = await client.post("/api/v1/routes/plan", json={"query": "徐汇区喝咖啡"})
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "owner@example.com",
            "password": "a-safe-password",
            "display_name": "Owner",
            "tenant_name": "Owner workspace",
        },
    )
    identity = registered.json()
    planned = await client.post(
        "/api/v1/routes/plan",
        json={
            "query": "徐汇区喝咖啡",
            "tenant_id": "forged-tenant",
            "user_id": "forged-user",
        },
    )

    assert anonymous.status_code == 401
    assert registered.status_code == 201
    assert "gentrip_access_token" in registered.headers["set-cookie"]
    assert (await client.get("/api/v1/auth/me")).status_code == 200
    assert planned.status_code == 200
    session_id = planned.json()["session_id"]
    session = await client.get(f"/api/v1/sessions/{session_id}")
    assert session.status_code == 200
    assert session.json()["tenant_id"] == identity["tenant"]["tenant_id"]
    assert session.json()["latest_response"] is not None


@pytest.mark.asyncio
async def test_authenticated_user_cannot_read_another_users_session(client, monkeypatch):
    _enable_auth(monkeypatch)
    first = await client.post(
        "/api/v1/auth/register",
        json={"email": "first@example.com", "password": "a-safe-password", "tenant_name": "First"},
    )
    assert first.status_code == 201
    planned = await client.post("/api/v1/routes/plan", json={"query": "黄浦区散步"})
    assert planned.status_code == 200
    session_id = planned.json()["session_id"]

    client.cookies.clear()
    second = await client.post(
        "/api/v1/auth/register",
        json={"email": "second@example.com", "password": "another-safe-password", "tenant_name": "Second"},
    )
    assert second.status_code == 201
    forbidden = await client.get(f"/api/v1/sessions/{session_id}")

    assert forbidden.status_code == 404


@pytest.mark.asyncio
async def test_login_rejects_invalid_password(client, monkeypatch):
    _enable_auth(monkeypatch)
    await client.post(
        "/api/v1/auth/register",
        json={"email": "login@example.com", "password": "a-safe-password", "tenant_name": "Login"},
    )
    client.cookies.clear()
    response = await client.post("/api/v1/auth/login", json={"email": "login@example.com", "password": "wrong-password"})

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_credentials"


@pytest.mark.asyncio
async def test_logout_revokes_the_bearer_token_and_session_can_be_revoked(client, monkeypatch):
    _enable_auth(monkeypatch)
    registered = await client.post(
        "/api/v1/auth/register",
        json={"email": "revoke@example.com", "password": "a-safe-password", "tenant_name": "Revoke"},
    )
    first_token = registered.json()["access_token"]
    client.cookies.clear()
    logged_in = await client.post(
        "/api/v1/auth/login",
        json={"email": "revoke@example.com", "password": "a-safe-password"},
    )
    second_token = logged_in.json()["access_token"]

    sessions = await client.get("/api/v1/auth/sessions", headers={"Authorization": f"Bearer {second_token}"})
    rows = sessions.json()["sessions"]
    first_session = next(row for row in rows if not row["current"])
    revoked = await client.delete(
        f"/api/v1/auth/sessions/{first_session['session_id']}",
        headers={"Authorization": f"Bearer {second_token}"},
    )
    first_after_revoke = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {first_token}"})
    logout = await client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {second_token}"})
    second_after_logout = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {second_token}"})

    assert sessions.status_code == 200
    assert len(rows) == 2
    assert revoked.status_code == 204
    assert first_after_revoke.status_code == 401
    assert first_after_revoke.json()["detail"] == "access_session_revoked"
    assert logout.status_code == 204
    assert second_after_logout.status_code == 401
