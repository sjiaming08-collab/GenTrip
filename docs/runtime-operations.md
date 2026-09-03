# Local Runtime Operations

Start the complete local runtime with:

```powershell
docker compose up -d --build
```

For a production-like single-host deployment, set a 32+ character
`AUTH_JWT_SECRET` and use both Compose files:

```powershell
docker compose -f docker-compose.yml -f docker-compose.production.yml up -d --build
```

The production override enables authentication and secure cookies, disables
public registration, and rejects request-provided tenant identifiers.

| Surface | URL | Purpose |
| --- | --- | --- |
| API health | `http://localhost:8080/api/v1/health` | API, Postgres, Redis readiness |
| Runtime metrics | `http://localhost:8080/api/v1/metrics` | Prometheus exposition |
| Prometheus | `http://localhost:9090` | Metrics and alert-rule inspection |
| Grafana | `http://localhost:3000` | Runtime dashboard and traces; local credentials default to `admin` / `admin` |
| Tempo | `http://localhost:3200/ready` | Trace backend readiness |

## Run diagnosis

Every asynchronous run has a durable record, ordered events, and safe checkpoints:

```text
GET  /api/v1/routes/plan/runs/{run_id}
GET  /api/v1/routes/plan/runs/{run_id}/checkpoints
POST /api/v1/routes/plan/runs/{run_id}/cancel
```

Checkpoints retain phase state, validation and tool/LLM metadata only. They do not contain raw prompts, model responses, or credentials. Use them to identify the last completed phase after a timeout or worker failure.

## DLQ operation

The Redis Stream worker retries each message up to `RUNTIME_QUEUE_MAX_ATTEMPTS` (default `3`). Exhausted work is copied to `RUNTIME_QUEUE_DEAD_LETTER_STREAM` and the corresponding run ends as `failed` with `worker_retry_exhausted`.

Tenant owners can inspect and replay an entry once:

```text
GET  /api/v1/runtime/dlq
POST /api/v1/runtime/dlq/{message_id}/replay
```

Replay keeps the original DLQ record for audit and creates a new stream message. It is intentionally one-shot for seven days, so an uncorrected poison message cannot loop indefinitely. Correct the dependency or input cause first.

## Runtime limits

| Setting | Default | Effect |
| --- | --- | --- |
| `RUNTIME_RUN_DEADLINE_SECONDS` | `120` | Whole graph execution deadline; produces terminal `timed_out` |
| `RUNTIME_TENANT_MAX_ACTIVE_RUNS` | `3` | Database-enforced per-tenant queued/running budget; excess requests receive HTTP `429` |
| `RUNTIME_QUEUE_CLAIM_IDLE_MS` | `150000` | Pending work is reclaimed after the 120s run deadline, avoiding duplicate live execution |
| `RUNTIME_QUEUE_HEARTBEAT_MS` | `30000` | Active workers refresh pending-message idle time during long graph/LLM execution |
| `RUNTIME_QUEUE_MAX_ATTEMPTS` | `3` | Retry count before DLQ |

Each completed graph node writes a versioned PostgreSQL checkpoint containing its serializable `GraphState` and the next routing target. After a retryable graph failure or worker interruption, a reclaimed Redis Stream message resumes at that next node when run, turn, tenant, session, and session-version checks all match. Invalid or legacy checkpoints fall back to a fresh graph execution. The checkpoint API exposes only the bounded diagnostic summary; the complete state remains internal to the worker.

This provides node-boundary continuation, not exactly-once side effects. A process can still stop after an external tool succeeds but before its checkpoint is committed, so tool providers must accept a stable idempotency key derived from `run_id + node + operation`.
