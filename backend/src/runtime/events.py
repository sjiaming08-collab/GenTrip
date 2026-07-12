"""Redis transport for transient runtime events and cancellation signals."""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator


class RuntimeEventBus:
    def __init__(self, redis_url: str = "") -> None:
        self.redis_url = redis_url
        self._client: Any = None
        self.available = False

    async def initialize(self) -> None:
        if self._client is not None or not self.redis_url:
            return
        try:
            import redis.asyncio as redis

            self._client = redis.from_url(self.redis_url, decode_responses=True)
            await self._client.ping()
            self.available = True
        except Exception:
            self._client = None
            self.available = False

    @staticmethod
    def _channel(run_id: str) -> str:
        return f"gentrip:run:{run_id}:events"

    @staticmethod
    def _cancel_key(run_id: str) -> str:
        return f"gentrip:run:{run_id}:cancelled"

    @staticmethod
    def _session_key(session_id: str) -> str:
        return f"gentrip:session:{session_id}"

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        await self.initialize()
        if not self.available:
            return None
        try:
            raw = await self._client.get(self._session_key(session_id))
            return json.loads(raw) if raw else None
        except Exception:
            return None

    async def cache_session(self, session_id: str, payload: dict[str, Any], *, ttl_seconds: int) -> None:
        await self.initialize()
        if not self.available:
            return
        try:
            await self._client.set(
                self._session_key(session_id),
                json.dumps(payload, ensure_ascii=False, default=str),
                ex=ttl_seconds,
            )
        except Exception:
            return

    async def publish(self, run_id: str, event: dict[str, Any]) -> None:
        await self.initialize()
        if self.available:
            await self._client.publish(self._channel(run_id), json.dumps(event, ensure_ascii=False, default=str))

    async def cancel(self, run_id: str) -> None:
        await self.initialize()
        if self.available:
            await self._client.set(self._cancel_key(run_id), "1", ex=3600)

    async def is_cancelled(self, run_id: str) -> bool:
        await self.initialize()
        return bool(self.available and await self._client.exists(self._cancel_key(run_id)))

    async def subscribe(self, run_id: str) -> AsyncIterator[dict[str, Any]]:
        await self.initialize()
        if not self.available:
            return
        pubsub = self._client.pubsub()
        await pubsub.subscribe(self._channel(run_id))
        try:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message.get("data"):
                    yield json.loads(message["data"])
                else:
                    await asyncio.sleep(0.05)
        finally:
            await pubsub.unsubscribe(self._channel(run_id))
            await pubsub.aclose()
