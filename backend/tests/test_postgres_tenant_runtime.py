"""Optional integration coverage for the local Postgres/PostGIS compose service."""

from uuid import uuid4

import pytest

from src.config import settings
from src.models.session import SessionState, Turn
from src.runtime.store import PostgresRuntimeStore, RunIdempotencyConflict


@pytest.mark.asyncio
@pytest.mark.runtime_integration
async def test_postgres_session_history_is_tenant_scoped():
    if not settings.database_url:
        pytest.skip("DATABASE_URL is not configured")

    store = PostgresRuntimeStore(settings.database_url)
    try:
        await store.initialize()
    except Exception as exc:
        pytest.skip(f"Postgres is unavailable: {exc}")

    session_id = f"tenant-it-{uuid4()}"
    alpha = SessionState(session_id=session_id, tenant_id="it-alpha", user_id="same-user", title="Alpha")
    alpha.add_turn(Turn(turn_id=str(uuid4()), user_query="alpha", reply_type="route"))
    beta = SessionState(session_id=session_id, tenant_id="it-beta", user_id="same-user", title="Beta")
    beta.add_turn(Turn(turn_id=str(uuid4()), user_query="beta", reply_type="route"))
    await store.save_session(alpha)
    await store.save_session(beta)

    assert (await store.load_session("it-alpha", session_id)).title == "Alpha"
    assert (await store.load_session("it-beta", session_id)).title == "Beta"
    assert await store.load_session("it-other", session_id) is None
    assert [turn.user_query for turn in await store.load_turns("it-alpha", session_id)] == ["alpha"]
    assert [turn.user_query for turn in await store.load_turns("it-beta", session_id)] == ["beta"]


@pytest.mark.asyncio
@pytest.mark.runtime_integration
async def test_postgres_first_turn_idempotency_is_tenant_scoped():
    if not settings.database_url:
        pytest.skip("DATABASE_URL is not configured")

    store = PostgresRuntimeStore(settings.database_url)
    await store.initialize()
    tenant = f"idempotency-it-{uuid4()}"
    key = f"request-{uuid4()}"
    first_run = str(uuid4())
    first_session = str(uuid4())
    await store.create_run(first_run, tenant, first_session, {"idempotency_key": key})

    existing = await store.find_run_by_idempotency(tenant, key)
    assert str(existing["run_id"]) == first_run
    assert existing["session_id"] == first_session

    with pytest.raises(RunIdempotencyConflict) as conflict:
        await store.create_run(str(uuid4()), tenant, str(uuid4()), {"idempotency_key": key})
    assert conflict.value.run_id == first_run
    assert conflict.value.session_id == first_session

    other_tenant_run = str(uuid4())
    await store.create_run(other_tenant_run, f"{tenant}-other", str(uuid4()), {"idempotency_key": key})
    assert await store.find_run_by_idempotency(f"{tenant}-other", key) is not None
