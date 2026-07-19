import pytest

from src.config import settings


def _enable_auth(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-auth-secret-that-is-long-enough-for-hs256")
    monkeypatch.setattr(settings, "tenant_api_keys_json", "")
    monkeypatch.setattr(settings, "allow_insecure_tenant_id", False)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_owner_manages_members_and_database_role_overrides_old_token(client, monkeypatch):
    _enable_auth(monkeypatch)
    owner = await client.post(
        "/api/v1/auth/register",
        json={"email": "owner@example.com", "password": "a-safe-password", "tenant_name": "Shared workspace"},
    )
    collaborator = await client.post(
        "/api/v1/auth/register",
        json={"email": "member@example.com", "password": "another-safe-password", "tenant_name": "Personal workspace"},
    )
    assert owner.status_code == 201
    assert collaborator.status_code == 201
    owner_body = owner.json()
    collaborator_body = collaborator.json()
    owner_token = owner_body["access_token"]
    owner_tenant_id = owner_body["tenant"]["tenant_id"]
    collaborator_id = collaborator_body["user"]["user_id"]

    added = await client.post(
        "/api/v1/tenants/current/members",
        headers=_bearer(owner_token),
        json={"email": "member@example.com", "role": "member"},
    )
    member_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "member@example.com", "password": "another-safe-password", "tenant_id": owner_tenant_id},
    )
    assert added.status_code == 201
    assert member_login.status_code == 200
    member_token = member_login.json()["access_token"]

    forbidden = await client.get("/api/v1/tenants/current/members", headers=_bearer(member_token))
    promoted = await client.patch(
        f"/api/v1/tenants/current/members/{collaborator_id}",
        headers=_bearer(owner_token),
        json={"role": "owner"},
    )
    # The old member token immediately observes its promoted database role.
    allowed = await client.get("/api/v1/tenants/current/members", headers=_bearer(member_token))
    workspaces = await client.get("/api/v1/auth/workspaces", headers=_bearer(member_token))
    audit_events = await client.get("/api/v1/tenants/current/audit-events", headers=_bearer(owner_token))
    demoted = await client.patch(
        f"/api/v1/tenants/current/members/{collaborator_id}",
        headers=_bearer(owner_token),
        json={"role": "member"},
    )
    last_owner = await client.delete(
        f"/api/v1/tenants/current/members/{owner_body['user']['user_id']}",
        headers=_bearer(owner_token),
    )

    assert forbidden.status_code == 403
    assert promoted.status_code == 204
    assert allowed.status_code == 200
    assert {member["email"] for member in allowed.json()["members"]} == {"owner@example.com", "member@example.com"}
    assert workspaces.status_code == 200
    assert len(workspaces.json()["workspaces"]) == 2
    assert audit_events.status_code == 200
    assert {event["action"] for event in audit_events.json()["events"]} >= {
        "auth.register",
        "tenant.member_added",
        "tenant.member_role_updated",
    }
    assert demoted.status_code == 204
    assert last_owner.status_code == 422


@pytest.mark.asyncio
async def test_member_can_switch_to_an_assigned_workspace(client, monkeypatch):
    _enable_auth(monkeypatch)
    owner = await client.post(
        "/api/v1/auth/register",
        json={"email": "switch-owner@example.com", "password": "a-safe-password", "tenant_name": "Team"},
    )
    member = await client.post(
        "/api/v1/auth/register",
        json={"email": "switch-member@example.com", "password": "another-safe-password", "tenant_name": "Personal"},
    )
    owner_body = owner.json()
    await client.post(
        "/api/v1/tenants/current/members",
        headers=_bearer(owner_body["access_token"]),
        json={"email": "switch-member@example.com"},
    )

    switched = await client.post(
        "/api/v1/auth/switch-workspace",
        headers=_bearer(member.json()["access_token"]),
        json={"tenant_id": owner_body["tenant"]["tenant_id"]},
    )

    assert switched.status_code == 200
    assert switched.json()["tenant"]["tenant_id"] == owner_body["tenant"]["tenant_id"]
    assert switched.json()["tenant"]["role"] == "member"
