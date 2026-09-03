"""Redis Stream worker entrypoint for durable Plan Run execution."""

from __future__ import annotations

import asyncio
import logging
import os
import socket

from .config import settings
from .llm.client import close_llm_client
from .runtime.task_queue import QueueFailureResult, QueueUnavailable, QueuedPlanRun, RedisPlanTaskQueue
from .runtime.session_summary_queue import QueuedSessionSummary, RedisSessionSummaryQueue
from .services.plan_service import PlanService
from .observability.tracing import configure_tracing

logger = logging.getLogger("gentrip.worker")


async def _heartbeat(queue: RedisPlanTaskQueue, consumer: str, message_id: str) -> None:
    interval = max(100, settings.runtime_queue_heartbeat_ms) / 1000
    while True:
        await asyncio.sleep(interval)
        try:
            if not await queue.touch(consumer, message_id):
                logger.warning("plan queue heartbeat lost message=%s consumer=%s", message_id, consumer)
        except QueueUnavailable:
            logger.warning("plan queue heartbeat unavailable message=%s consumer=%s", message_id, consumer)


async def process_message(
    service: PlanService,
    queue: RedisPlanTaskQueue,
    message: QueuedPlanRun,
    *,
    consumer: str | None = None,
) -> QueueFailureResult | None:
    """Process one stream message while preserving at-least-once delivery semantics."""
    heartbeat = asyncio.create_task(_heartbeat(queue, consumer, message.message_id)) if consumer else None
    try:
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
    finally:
        if heartbeat:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)


async def process_summary_message(
    service: PlanService,
    queue: RedisSessionSummaryQueue,
    job: QueuedSessionSummary,
) -> QueueFailureResult | None:
    try:
        latest_turn_id = await service.execute_session_summary(job)
        if latest_turn_id and latest_turn_id != job.target_turn_id:
            await queue.enqueue(job.tenant_id, job.session_id, latest_turn_id, job.run_id)
        await queue.acknowledge(job.message_id)
        return None
    except Exception as exc:
        logger.exception("session summary job failed message=%s", job.message_id)
        return await queue.handle_failure(job, f"{type(exc).__name__}: {exc}")


async def _run_summary_worker(
    service: PlanService,
    queue: RedisSessionSummaryQueue,
    consumer: str,
) -> None:
    while True:
        try:
            await queue.ensure_group()
            break
        except Exception:
            logger.exception("session summary queue initialization failed")
            await asyncio.sleep(1.0)
    logger.info("session summary worker started consumer=%s", consumer)
    while True:
        try:
            reclaimed = await queue.reclaim(consumer, count=5)
            jobs = reclaimed or await queue.read(consumer)
            for job in jobs:
                await process_summary_message(service, queue, job)
        except Exception:
            logger.exception("session summary queue read failed")
            await asyncio.sleep(1.0)


async def run_worker() -> None:
    configure_tracing("gentrip-worker")
    service = PlanService()
    queue = RedisPlanTaskQueue()
    summary_queue = RedisSessionSummaryQueue()
    consumer = os.getenv("RUNTIME_WORKER_NAME") or f"{socket.gethostname()}-{os.getpid()}"
    await service.initialize()
    await queue.ensure_group()
    logger.info("plan worker started consumer=%s", consumer)

    summary_worker = asyncio.create_task(
        _run_summary_worker(service, summary_queue, f"{consumer}-summary"),
        name="gentrip-session-summary-worker",
    )
    try:
        while True:
            reclaimed = await queue.reclaim(consumer, count=5)
            messages = reclaimed or await queue.read(consumer, count=1)
            for message in messages:
                await process_message(service, queue, message, consumer=consumer)
    finally:
        summary_worker.cancel()
        await asyncio.gather(summary_worker, return_exceptions=True)
        await close_llm_client()


def main() -> None:
    try:
        asyncio.run(run_worker())
    except QueueUnavailable as exc:
        raise SystemExit(f"plan worker queue unavailable: {exc}") from exc


if __name__ == "__main__":
    main()
