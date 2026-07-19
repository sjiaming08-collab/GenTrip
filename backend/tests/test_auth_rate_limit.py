import pytest
from fastapi import HTTPException

from src.api.routes import login_rate_limiter
from src.config import settings


class FakeRedis:
    def __init__(self):
        self.values: dict[str, int] = {}

    async def get(self, key: str):
        return self.values.get(key)

    async def incr(self, key: str):
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def expire(self, key: str, seconds: int):
        return True

    async def delete(self, key: str):
        self.values.pop(key, None)


@pytest.mark.asyncio
async def test_rate_limiter_blocks_after_configured_failed_attempts(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(settings, "auth_login_rate_limit_enabled", True)
    monkeypatch.setattr(settings, "auth_login_max_attempts", 2)
    login_rate_limiter._client = fake
    login_rate_limiter._available = True

    await login_rate_limiter.check("user@example.com", "127.0.0.1")
    await login_rate_limiter.record_failure("user@example.com", "127.0.0.1")
    await login_rate_limiter.record_failure("user@example.com", "127.0.0.1")
    with pytest.raises(HTTPException) as exc:
        await login_rate_limiter.check("user@example.com", "127.0.0.1")
    await login_rate_limiter.reset("user@example.com", "127.0.0.1")
    await login_rate_limiter.check("user@example.com", "127.0.0.1")

    assert exc.value.status_code == 429
    assert exc.value.detail == "too_many_login_attempts"
