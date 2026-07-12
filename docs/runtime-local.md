# Local Runtime

The local runtime uses Postgres for sessions, runs, and append-only events. Redis is used for event publication and cooperative cancellation. Docker Compose starts both dependencies and the API.

## Start

1. Install Docker Desktop with its WSL2 backend, then restart Windows if the installer requests it.
2. Copy `.env.example` to `.env` and set optional LLM variables there.
3. Run `docker compose up --build` from the repository root.

The API is available at `http://localhost:8080/api/v1/health`. The first start applies `backend/migrations/001_runtime.sql` automatically.

## Runtime API

- `POST /api/v1/routes/plan` runs synchronously and returns a complete result.
- `POST /api/v1/routes/plan/runs` returns `202` with a `run_id` for a background run.
- `GET /api/v1/routes/plan/runs/{run_id}` returns run status and its final result.
- `GET /api/v1/routes/plan/runs/{run_id}/events` is an SSE stream. It honors `Last-Event-ID` and replays persisted events.
- `POST /api/v1/routes/plan/runs/{run_id}/cancel` requests cooperative cancellation.

When Redis is unavailable, persisted event polling still serves SSE replay and progress. When Postgres is unavailable, the API readiness result is degraded and durable run operations should not be used.
