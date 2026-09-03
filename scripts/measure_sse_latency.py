"""Measure client-visible latency for the persisted Plan Run SSE endpoint."""

from __future__ import annotations

import argparse
import json
import statistics
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(len(ordered) * quantile + 0.999999) - 1))
    return ordered[index]


def parse_created_at(value: Any) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def consume_sse(response: httpx.Response):
    event_type = "message"
    data_lines: list[str] = []
    for line in response.iter_lines():
        if not line:
            if data_lines:
                yield event_type, json.loads("\n".join(data_lines)), time.time(), time.perf_counter()
            event_type = "message"
            data_lines = []
            continue
        if line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())


def measure_once(client: httpx.Client, base_url: str, tenant_id: str, query: str) -> dict[str, Any]:
    started_perf = time.perf_counter()
    started_wall = time.time()
    started = client.post(
        f"{base_url}/api/v1/routes/plan/runs",
        json={
            "query": query,
            "tenant_id": tenant_id,
            "user_id": "sse-latency-user",
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    started.raise_for_status()
    accepted_perf = time.perf_counter()
    run_id = started.json()["run_id"]

    first_event_perf: float | None = None
    first_phase_completed_perf: float | None = None
    complete_perf: float | None = None
    delivery_lags_ms: list[float] = []
    phase_events = 0

    with client.stream(
        "GET",
        f"{base_url}/api/v1/routes/plan/runs/{run_id}/events",
        params={"tenant_id": tenant_id},
        headers={"Accept": "text/event-stream"},
    ) as stream:
        stream.raise_for_status()
        headers_perf = time.perf_counter()
        for event_type, payload, received_wall, received_perf in consume_sse(stream):
            if first_event_perf is None:
                first_event_perf = received_perf
            if event_type == "phase":
                phase_events += 1
                if payload.get("status") == "completed" and first_phase_completed_perf is None:
                    first_phase_completed_perf = received_perf
                created_at = parse_created_at(payload.get("created_at") or payload.get("ts"))
                if created_at is not None:
                    delivery_lags_ms.append(max(0.0, (received_wall - created_at) * 1000))
            elif event_type == "complete":
                complete_perf = received_perf
                terminal_status = payload.get("status")
                break
        else:
            terminal_status = "stream_closed"

    if first_event_perf is None or complete_perf is None:
        raise RuntimeError(f"SSE stream ended without required events for run {run_id}")
    return {
        "run_id": run_id,
        "terminal_status": terminal_status,
        "submit_ms": (accepted_perf - started_perf) * 1000,
        "sse_headers_ms": (headers_perf - accepted_perf) * 1000,
        "first_event_from_submit_ms": (first_event_perf - started_perf) * 1000,
        "first_event_after_subscribe_ms": (first_event_perf - accepted_perf) * 1000,
        "first_phase_completed_ms": (
            (first_phase_completed_perf - started_perf) * 1000 if first_phase_completed_perf else None
        ),
        "complete_ms": (complete_perf - started_perf) * 1000,
        "phase_event_count": phase_events,
        "event_delivery_avg_ms": statistics.fmean(delivery_lags_ms) if delivery_lags_ms else None,
        "event_delivery_max_ms": max(delivery_lags_ms) if delivery_lags_ms else None,
        "started_at_epoch": started_wall,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = [
        "submit_ms",
        "sse_headers_ms",
        "first_event_from_submit_ms",
        "first_event_after_subscribe_ms",
        "first_phase_completed_ms",
        "complete_ms",
        "event_delivery_avg_ms",
        "event_delivery_max_ms",
    ]
    summary: dict[str, Any] = {"samples": len(rows)}
    for metric in metrics:
        values = [float(row[metric]) for row in rows if row.get(metric) is not None]
        if values:
            summary[metric] = {
                "average": round(statistics.fmean(values), 3),
                "p50": round(percentile(values, 0.50), 3),
                "p95": round(percentile(values, 0.95), 3),
                "max": round(max(values), 3),
            }
    summary["terminal_statuses"] = {
        status: sum(row["terminal_status"] == status for row in rows)
        for status in sorted({str(row["terminal_status"]) for row in rows})
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--query", default="黄浦区朋友聚会，人均100元，玩3小时")
    parser.add_argument("--tenant-prefix", default="sse-latency")
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.samples < 1:
        raise SystemExit("--samples must be at least 1")

    rows: list[dict[str, Any]] = []
    with httpx.Client(timeout=args.timeout_seconds, trust_env=False) as client:
        for index in range(args.samples):
            tenant_id = f"{args.tenant_prefix}-{index + 1}"
            row = measure_once(client, args.base_url.rstrip("/"), tenant_id, args.query)
            rows.append(row)
            delivery = row["event_delivery_avg_ms"]
            delivery_text = f"{delivery:.1f}" if delivery is not None else "n/a"
            print(
                f"sample={index + 1} first_event_ms={row['first_event_from_submit_ms']:.1f} "
                f"delivery_avg_ms={delivery_text} complete_ms={row['complete_ms']:.1f}"
            )

    result = {"summary": summarize(rows), "samples": rows}
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
