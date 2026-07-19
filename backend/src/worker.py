"""Redis Stream worker entrypoint for durable Plan Run execution."""

from __future__ import annotations

import asyncio
import logging
import os
import socket

from .runtime.task_queue import QueueFailureResult, QueueUnavailable, QueuedPlanRun, RedisPlanTaskQueue
from .services.plan_service import PlanService
from .observability.tracing import configure_tracing

logger = logging.getLogger("gentrip.worker")


async def process_message(service: PlanService, queue: RedisPlanTaskQueue, message: QueuedPlanRun) -> QueueFailureResult | None:
    """Process one stream message while preserving at-least-once delivery semantics."""
    try:
        await service.execute_queued_run(message.initial, message.session)
    except Exception as exc:
        logger.exception("worker failed processing queue message %s", message.message_id)
        failure = await queue.handle_failure(message, f"{type(exc).__name__}: {exc}")
        if failure.dead_lettered:
            await service.fail_queued_run(message.initial, message.session, error_code="worker_retry_exhausted")
            logger.error("plan queue message %s moved to DLQ after %s attempts", message.message_id, failure.attempt)
        return failure
    await queue.acknowledge(message.message_id)
    return None


async def run_worker() -> None:
    configure_tracing("gentrip-worker")
    service = PlanService()
    queue = RedisPlanTaskQueue()
    consumer = os.getenv("RUNTIME_WORKER_NAME") or f"{socket.gethostname()}-{os.getpid()}"
    await service.initialize()
    await queue.ensure_group()
    logger.info("plan worker started consumer=%s", consumer)

    while True:
        reclaimed = await queue.reclaim(consumer, count=5)
        messages = reclaimed or await queue.read(consumer, count=1)
        for message in messages:
            await process_message(service, queue, message)


def main() -> None:
    try:
        asyncio.run(run_worker())
    except QueueUnavailable as exc:
        raise SystemExit(f"plan worker queue unavailable: {exc}") from exc


if __name__ == "__main__":
    main()
