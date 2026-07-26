"""Durable Plan Run dispatch over Redis Streams."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from ..config import settings


class QueueUnavailable(RuntimeError):
    """Raised when configured durable execution cannot accept a run."""


@dataclass(frozen=True)
class QueuedPlanRun:
    message_id: str
    initial: dict[str, Any]
    session: dict[str, Any]


@dataclass(frozen=True)
class QueueFailureResult:
    attempt: int
    dead_lettered: bool


@dataclass(frozen=True)
class DeadLetterPlanRun:
    message_id: str
    source_message_id: str
    attempt: int
    error: str
    initial: dict[str, Any]
    session: dict[str, Any]


class PlanTaskQueue(Protocol):
    async def enqueue(self, initial: dict[str, Any], session: dict[str, Any]) -> str: ...


class RedisPlanTaskQueue:
    def __init__(self, *, stream: str | None = None, group: str | None = None, dead_letter_stream: str | None = None) -> None:
        self.stream = stream or settings.runtime_queue_stream
        self.group = group or settings.runtime_queue_group
        self.dead_letter_stream = dead_letter_stream or settings.runtime_queue_dead_letter_stream

    @property
    def _attempts_key(self) -> str:
        return f"{self.stream}:attempts"

    @staticmethod
    def _client(*, socket_timeout: float = 2.0):
        if not settings.redis_url:
            raise QueueUnavailable("REDIS_URL is required for redis_stream execution")
        import redis.asyncio as redis

        return redis.from_url(
            settings.redis_url,
            decode_responses=True,
            protocol=2,
            socket_connect_timeout=0.5,
            socket_timeout=socket_timeout,
        )

    async def enqueue(self, initial: dict[str, Any], session: dict[str, Any]) -> str:
        try:
            client = self._client()
            try:
                message_id = await client.xadd(
                    self.stream,
                    {"initial": json.dumps(initial, ensure_ascii=False), "session": json.dumps(session, ensure_ascii=False)},
                )
            finally:
                await client.aclose()
            return str(message_id)
        except QueueUnavailable:
            raise
        except Exception as exc:
            raise QueueUnavailable("unable to enqueue plan run") from exc

    async def ensure_group(self) -> None:
        try:
            client = self._client()
            try:
                try:
                    await client.xgroup_create(self.stream, self.group, id="0", mkstream=True)
                except Exception as exc:
                    if "BUSYGROUP" not in str(exc):
                        raise
            finally:
                await client.aclose()
        except QueueUnavailable:
            raise
        except Exception as exc:
            raise QueueUnavailable("unable to initialize plan worker group") from exc

    async def read(self, consumer: str, *, block_ms: int = 5000, count: int = 1) -> list[QueuedPlanRun]:
        try:
            # Redis must be allowed to outlive XREADGROUP's server-side block.
            client = self._client(socket_timeout=max(2.0, block_ms / 1000 + 1.0))
            try:
                raw = await client.xreadgroup(
                    self.group,
                    consumer,
                    {self.stream: ">"},
                    count=count,
                    block=block_ms,
                )
            finally:
                await client.aclose()
        except QueueUnavailable:
            raise
        except Exception as exc:
            raise QueueUnavailable("unable to read plan queue") from exc
        return self._parse(raw)

    @staticmethod
    def _parse(raw: list[Any]) -> list[QueuedPlanRun]:
        result: list[QueuedPlanRun] = []
        for _stream, messages in raw or []:
            for message_id, fields in messages:
                try:
                    result.append(
                        QueuedPlanRun(
                            message_id=str(message_id),
                            initial=json.loads(fields["initial"]),
                            session=json.loads(fields["session"]),
                        )
                    )
                except (KeyError, TypeError, json.JSONDecodeError):
                    # A malformed message must be acknowledged by the worker so it cannot block the stream forever.
                    result.append(QueuedPlanRun(message_id=str(message_id), initial={}, session={}))
        return result

    async def reclaim(self, consumer: str, *, min_idle_ms: int | None = None, count: int = 10) -> list[QueuedPlanRun]:
        """Claim abandoned pending messages after a worker crash or restart."""
        try:
            client = self._client()
            try:
                raw = await client.xautoclaim(
                    self.stream,
                    self.group,
                    consumer,
                    min_idle_time=min_idle_ms or settings.runtime_queue_claim_idle_ms,
                    start_id="0-0",
                    count=count,
                )
            finally:
                await client.aclose()
        except QueueUnavailable:
            raise
        except Exception as exc:
            raise QueueUnavailable("unable to reclaim plan queue messages") from exc
        messages = raw[1] if isinstance(raw, (list, tuple)) and len(raw) > 1 else []
        return self._parse([(self.stream, messages)])

    async def acknowledge(self, message_id: str) -> None:
        client = self._client()
        try:
            await client.xack(self.stream, self.group, message_id)
        finally:
            await client.aclose()

    async def handle_failure(self, message: QueuedPlanRun, error: str) -> QueueFailureResult:
        """Record a failed attempt and atomically move exhausted work to the DLQ."""
        try:
            client = self._client()
            try:
                attempt = int(await client.hincrby(self._attempts_key, message.message_id, 1))
                if attempt < settings.runtime_queue_max_attempts:
                    return QueueFailureResult(attempt=attempt, dead_lettered=False)
                pipe = client.pipeline(transaction=True)
                pipe.xadd(
                    self.dead_letter_stream,
                    {
                        "source_stream": self.stream,
                        "source_message_id": message.message_id,
                        "attempt": str(attempt),
                        "error": error[:500],
                        "initial": json.dumps(message.initial, ensure_ascii=False),
                        "session": json.dumps(message.session, ensure_ascii=False),
                    },
                )
                pipe.xack(self.stream, self.group, message.message_id)
                pipe.hdel(self._attempts_key, message.message_id)
                await pipe.execute()
                return QueueFailureResult(attempt=attempt, dead_lettered=True)
            finally:
                await client.aclose()
        except QueueUnavailable:
            raise
        except Exception as exc:
            raise QueueUnavailable("unable to record plan queue failure") from exc

    @staticmethod
    def _parse_dead_letters(raw: list[Any]) -> list[DeadLetterPlanRun]:
        entries: list[DeadLetterPlanRun] = []
        for message_id, fields in raw or []:
            try:
                entries.append(
                    DeadLetterPlanRun(
                        message_id=str(message_id),
                        source_message_id=str(fields["source_message_id"]),
                        attempt=int(fields.get("attempt", 0)),
                        error=str(fields.get("error", "")),
                        initial=json.loads(fields["initial"]),
                        session=json.loads(fields["session"]),
                    )
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return entries

    async def list_dead_letters(self, *, limit: int = 100) -> list[DeadLetterPlanRun]:
        try:
            client = self._client()
            try:
                raw = await client.xrevrange(self.dead_letter_stream, max="+", min="-", count=limit)
            finally:
                await client.aclose()
        except QueueUnavailable:
            raise
        except Exception as exc:
            raise QueueUnavailable("unable to list plan queue DLQ") from exc
        return self._parse_dead_letters(raw)

    async def replay_dead_letter(self, message_id: str) -> str:
        """Requeue an exhausted payload once while retaining the DLQ audit entry."""
        try:
            client = self._client()
            try:
                rows = await client.xrange(self.dead_letter_stream, min=message_id, max=message_id, count=1)
                entries = self._parse_dead_letters(rows)
                if not entries:
                    raise KeyError("dead_letter_not_found")
                replay_key = f"{self.dead_letter_stream}:replayed:{message_id}"
                if not await client.set(replay_key, "1", nx=True, ex=7 * 24 * 3600):
                    raise ValueError("dead_letter_already_replayed")
                entry = entries[0]
                try:
                    return str(
                        await client.xadd(
                            self.stream,
                            {
                                "initial": json.dumps(entry.initial, ensure_ascii=False),
                                "session": json.dumps(entry.session, ensure_ascii=False),
                                "replayed_from": message_id,
                            },
                        )
                    )
                except Exception:
                    await client.delete(replay_key)
                    raise
            finally:
                await client.aclose()
        except (KeyError, ValueError):
            raise
        except QueueUnavailable:
            raise
        except Exception as exc:
            raise QueueUnavailable("unable to replay plan queue DLQ message") from exc
