"""Redis-backed protection for credential endpoints."""

from __future__ import annotations

import hashlib
from typing import Any

from fastapi import HTTPException

from ..config import settings


class LoginRateLimiter:
    """Counts failures across API processes without storing raw email addresses."""

    def __init__(self) -> None:
        self._client: Any = None
        self._available = False

    async def _initialize(self) -> bool:
        if self._client is not None:
            return self._available
        if not settings.redis_url:
            return False
        try:
            import redis.asyncio as redis

            self._client = redis.from_url(settings.redis_url, decode_responses=True, protocol=2)
            await self._client.ping()
            self._available = True
        except Exception:
            self._client = None
            self._available = False
        return self._available

    @staticmethod
    def _key(email: str, client_ip: str) -> str:
        digest = hashlib.sha256(f"{email.lower()}\0{client_ip}".encode("utf-8")).hexdigest()
        return f"gentrip:auth:login-failures:{digest}"

    async def _require_client(self) -> Any:
        if not settings.auth_login_rate_limit_enabled:
            return None
        if not await self._initialize():
            raise HTTPException(status_code=503, detail="auth_rate_limiter_unavailable")
        return self._client

    async def check(self, email: str, client_ip: str) -> None:
        client = await self._require_client()
        if client is None:
            return
        count = int(await client.get(self._key(email, client_ip)) or 0)
        if count >= settings.auth_login_max_attempts:
            raise HTTPException(status_code=429, detail="too_many_login_attempts")

    async def record_failure(self, email: str, client_ip: str) -> None:
        client = await self._require_client()
        if client is None:
            return
        key = self._key(email, client_ip)
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, settings.auth_login_window_seconds)

    async def reset(self, email: str, client_ip: str) -> None:
        client = await self._require_client()
        if client is not None:
            await client.delete(self._key(email, client_ip))
