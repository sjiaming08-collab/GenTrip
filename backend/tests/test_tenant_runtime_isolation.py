import pytest

from src.config import settings
from src.models.profile import UserProfile
from src.models.session import SessionState, Turn
from src.runtime.events import RuntimeEventBus
from src.runtime.store import MemoryRuntimeStore


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, tuple[str, int | None]] = {}

    async def set(self, key: str, value: str, *, ex: int | None = None) -> None:
        self.values[key] = (value, ex)

    async def get(self, key: str) -> str | None:
        item = self.values.get(key)
        return item[0] if item else None


@pytest.mark.asyncio
async def test_memory_store_scopes_sessions_turns_and_runs_by_tenant():
    store = MemoryRuntimeStore()
    session_id = "shared-session"
    alpha = SessionState(session_id=session_id, tenant_id="alpha", user_id="same-user", title="Alpha")
    alpha.add_turn(Turn(turn_id="00000000-0000-0000-0000-000000000001", user_query="alpha", reply_type="route"))
    beta = SessionState(session_id=session_id, tenant_id="beta", user_id="same-user", title="Beta")
    beta.add_turn(Turn(turn_id="00000000-0000-0000-0000-000000000002", user_query="beta", reply_type="route"))
    await store.save_session(alpha)
    await store.save_session(beta)

    assert (await store.load_session("alpha", session_id)).title == "Alpha"
    assert (await store.load_session("beta", session_id)).title == "Beta"
    assert await store.load_session("other", session_id) is None
    assert [turn.user_query for turn in await store.load_turns("alpha", session_id)] == ["alpha"]
    assert [turn.user_query for turn in await store.load_turns("beta", session_id)] == ["beta"]
    assert [item["title"] for item in await store.list_sessions("alpha", "same-user", 10)] == ["Alpha"]

    run_id = "00000000-0000-0000-0000-000000000010"
    await store.create_run(run_id, "alpha", session_id, {"query": "alpha"})
    assert await store.get_run("alpha", run_id) is not None
    assert await store.get_run("beta", run_id) is None
    await store.append_event("alpha", run_id, {"phase": "runtime", "status": "queued"})
    assert len(await store.get_events_after("alpha", run_id, 0)) == 1
    assert await store.get_events_after("beta", run_id, 0) == []

    alpha_profile = UserProfile.create_default("same-user")
    alpha_profile.preferred_districts = ["徐汇区"]
    beta_profile = UserProfile.create_default("same-user")
    beta_profile.preferred_districts = ["黄浦区"]
    await store.save_profile("alpha", alpha_profile)
    await store.save_profile("beta", beta_profile)
    assert (await store.load_profile("alpha", "same-user")).preferred_districts == ["徐汇区"]
    assert (await store.load_profile("beta", "same-user")).preferred_districts == ["黄浦区"]


def test_redis_session_cache_keys_are_tenant_scoped():
    assert RuntimeEventBus._session_key("alpha", "shared-session") != RuntimeEventBus._session_key("beta", "shared-session")
    assert "shared-session" in RuntimeEventBus._session_key("alpha", "shared-session")


@pytest.mark.asyncio
async def test_redis_session_cache_uses_tenant_key_and_ttl():
    bus = RuntimeEventBus()
    fake = _FakeRedis()
    bus._client = fake
    bus.available = True

    await bus.cache_session("alpha", "shared-session", {"tenant_id": "alpha", "title": "Alpha"}, ttl_seconds=123)
    await bus.cache_session("beta", "shared-session", {"tenant_id": "beta", "title": "Beta"}, ttl_seconds=123)

    alpha_key = RuntimeEventBus._session_key("alpha", "shared-session")
    beta_key = RuntimeEventBus._session_key("beta", "shared-session")
    assert fake.values[alpha_key][1] == 123
    assert fake.values[beta_key][1] == 123
    assert (await bus.get_session("alpha", "shared-session"))["title"] == "Alpha"
    assert (await bus.get_session("beta", "shared-session"))["title"] == "Beta"


@pytest.mark.asyncio
@pytest.mark.runtime_integration
async def test_real_redis_session_cache_is_tenant_scoped_when_configured():
    if not settings.redis_url:
        pytest.skip("REDIS_URL is not configured")
    bus = RuntimeEventBus(settings.redis_url)
    await bus.initialize()
    if not bus.available:
        pytest.skip("Redis is unavailable")

    session_id = "tenant-runtime-integration"
    try:
        await bus.cache_session("redis-alpha", session_id, {"tenant_id": "redis-alpha"}, ttl_seconds=60)
        await bus.cache_session("redis-beta", session_id, {"tenant_id": "redis-beta"}, ttl_seconds=60)
        assert (await bus.get_session("redis-alpha", session_id))["tenant_id"] == "redis-alpha"
        assert (await bus.get_session("redis-beta", session_id))["tenant_id"] == "redis-beta"
        assert await bus._client.ttl(RuntimeEventBus._session_key("redis-alpha", session_id)) > 0
    finally:
        if bus._client is not None:
            await bus._client.delete(
                RuntimeEventBus._session_key("redis-alpha", session_id),
                RuntimeEventBus._session_key("redis-beta", session_id),
            )
            await bus._client.aclose()


@pytest.mark.asyncio
async def test_session_api_does_not_read_another_tenant(client):
    session_id = "tenant-api-shared"
    planned = await client.post(
        "/api/v1/routes/plan",
        json={"query": "徐汇区喝咖啡", "session_id": session_id, "tenant_id": "alpha", "user_id": "user-a"},
    )
    assert planned.status_code == 200

    own = await client.get(f"/api/v1/sessions/{session_id}", params={"tenant_id": "alpha"})
    other = await client.get(f"/api/v1/sessions/{session_id}", params={"tenant_id": "beta"})
    assert own.status_code == 200
    assert own.json()["tenant_id"] == "alpha"
    assert other.status_code == 404
