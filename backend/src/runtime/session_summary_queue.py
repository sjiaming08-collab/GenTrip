"""Durable background session-summary jobs over Redis Streams."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config import settings
from .task_queue import QueueFailureResult, QueueUnavailable


@dataclass(frozen=True)
class QueuedSessionSummary:
    message_id: str
    tenant_id: str
    session_id: str
    target_turn_id: str
    run_id: str


class RedisSessionSummaryQueue:
    def __init__(self) -> None:
        self.stream = settings.session_summary_queue_stream
        self.group = settings.session_summary_queue_group

    @property
    def _attempts_key(self) -> str:
        return f"{self.stream}:attempts"

    @staticmethod
    def _client(*, socket_timeout: float = 2.0):
        if not settings.redis_url:
            raise QueueUnavailable("REDIS_URL is required for async session summaries")
        import redis.asyncio as redis

        return redis.from_url(
            settings.redis_url,
            decode_responses=True,
            protocol=2,
            socket_connect_timeout=0.5,
            socket_timeout=socket_timeout,
        )

    async def ensure_group(self) -> None:
        client = self._client()
        try:
            try:
                await client.xgroup_create(self.stream, self.group, id="0", mkstream=True)
            except Exception as exc:
                if "BUSYGROUP" not in str(exc):
                    raise
        finally:
            await client.aclose()

    async def enqueue(self, tenant_id: str, session_id: str, target_turn_id: str, run_id: str) -> str:
        client = self._client()
        try:
            return str(await client.xadd(self.stream, {
                "tenant_id": tenant_id,
                "session_id": session_id,
                "target_turn_id": target_turn_id,
                "run_id": run_id,
            }))
        finally:
            await client.aclose()

    @staticmethod
    def _parse(raw: list[Any]) -> list[QueuedSessionSummary]:
        jobs: list[QueuedSessionSummary] = []
        for _stream, messages in raw or []:
            for message_id, fields in messages:
                try:
                    jobs.append(QueuedSessionSummary(
                        message_id=str(message_id),
                        tenant_id=str(fields["tenant_id"]),
                        session_id=str(fields["session_id"]),
                        target_turn_id=str(fields["target_turn_id"]),
                        run_id=str(fields["run_id"]),
                    ))
                except (KeyError, TypeError):
                    continue
        return jobs

    async def read(self, consumer: str, *, block_ms: int = 5000) -> list[QueuedSessionSummary]:
        client = self._client(socket_timeout=max(2.0, block_ms / 1000 + 1.0))
        try:
            raw = await client.xreadgroup(
                self.group, consumer, {self.stream: ">"}, count=1, block=block_ms
            )
        finally:
            await client.aclose()
        return self._parse(raw)

    async def reclaim(self, consumer: str, *, count: int = 5) -> list[QueuedSessionSummary]:
        client = self._client()
        try:
            raw = await client.xautoclaim(
                self.stream,
                self.group,
                consumer,
                min_idle_time=settings.runtime_queue_claim_idle_ms,
                start_id="0-0",
                count=count,
            )
        finally:
            await client.aclose()
        messages = raw[1] if isinstance(raw, (list, tuple)) and len(raw) > 1 else []
        return self._parse([(self.stream, messages)])

    async def acknowledge(self, message_id: str) -> None:
        client = self._client()
        try:
            pipe = client.pipeline(transaction=True)
            pipe.xack(self.stream, self.group, message_id)
            pipe.hdel(self._attempts_key, message_id)
            await pipe.execute()
        finally:
            await client.aclose()

    async def handle_failure(self, job: QueuedSessionSummary, error: str) -> QueueFailureResult:
        client = self._client()
        try:
            attempt = int(await client.hincrby(self._attempts_key, job.message_id, 1))
            if attempt < settings.runtime_queue_max_attempts:
                return QueueFailureResult(attempt=attempt, dead_lettered=False)
            pipe = client.pipeline(transaction=True)
            pipe.xadd(settings.runtime_queue_dead_letter_stream, {
                "task_type": "session_summary",
                "source_stream": self.stream,
                "source_message_id": job.message_id,
                "attempt": str(attempt),
                "error": error[:500],
                "tenant_id": job.tenant_id,
                "session_id": job.session_id,
                "target_turn_id": job.target_turn_id,
                "run_id": job.run_id,
            })
            pipe.xack(self.stream, self.group, job.message_id)
            pipe.hdel(self._attempts_key, job.message_id)
            await pipe.execute()
            return QueueFailureResult(attempt=attempt, dead_lettered=True)
        finally:
            await client.aclose()
