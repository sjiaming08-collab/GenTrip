# Runtime Storage

## Lifecycle

`SessionState` is written synchronously to Postgres after every completed turn. The `sessions` table stores the current compact state, while `turns` stores every turn as durable conversation history. `user_profiles`, `runs`, and `run_events` are also durable Postgres records.

Redis is only a short-lived read cache for the current `SessionState`. It is populated after every database write and on a database read-through miss. `RUNTIME_SESSION_CACHE_TTL_SECONDS` controls expiry and defaults to 24 hours. Redis loss or expiry only causes a Postgres read; it cannot lose conversation history.

## Tenant Isolation

Every public session operation accepts `tenant_id`, defaulting to `default` for local backwards compatibility. The database migration `005_tenant_runtime.sql` scopes sessions, turns, runs, and profiles by tenant. Redis uses the key form:

```text
gentrip:tenant:<url-encoded-tenant-id>:session:<url-encoded-session-id>
```

The same `session_id` and `user_id` can therefore exist in different tenants without sharing cached state, database rows, run status, SSE events, or profiles.

When `TENANT_API_KEYS_JSON` is configured, `X-API-Key` is required and the server derives `tenant_id` from that mapping, ignoring request tenant fields. For local development only, `ALLOW_INSECURE_TENANT_ID=true` retains the old request-field fallback. Set it to `false` in production so a missing API-key mapping fails closed.

## Local Verification

```powershell
D:\conda3\envs\GenTrip\python.exe -m pytest backend/tests/test_tenant_runtime_isolation.py -q
D:\conda3\envs\GenTrip\python.exe -m pytest backend/tests/test_postgres_tenant_runtime.py -q
```

The Postgres test skips when `DATABASE_URL` is unavailable or Postgres is not reachable. Once Docker Desktop is running and `docker compose up -d postgres redis` succeeds, it applies migration `005_tenant_runtime.sql` automatically during store initialization.
## RouteBundle Cache

`RouteBundle` uses an in-process TTL cache first and Redis second. Only routes scored by deterministic rules are written, so LLM/profile-specific ranking is never shared across users. Redis keys are SHA-256 hashes of canonicalized feasibility constraints and expire after `ROUTE_BUNDLE_CACHE_TTL_SECONDS` (default 1800 seconds). If Redis is unavailable, planning continues on the local cache or cold path.

After an exact-key miss, the cache also evaluates a structured constraint feature vector. It requires the same district, domains, explicit cuisines, and exclusions, then scores budget, duration, start/return time, queue tolerance, and POI count. Scores below `ROUTE_BUNDLE_MIN_MATCH_SCORE` (default `0.85`) stay on the cold path. Similarity hits are labelled `BUNDLE_ADAPTED` and still pass current-request route validation; this is not a general natural-language embedding index.

## Durable Worker

Set `RUNTIME_EXECUTION_MODE=redis_stream` to route `POST /routes/plan/runs` through Redis Stream `RUNTIME_QUEUE_STREAM`. The API creates the durable run and session before enqueueing. `python -m src.worker` consumes via a Redis consumer group, acknowledges only after execution, and reclaims abandoned pending messages after `RUNTIME_QUEUE_CLAIM_IDLE_MS`. A failed message remains pending for retry; after `RUNTIME_QUEUE_MAX_ATTEMPTS` failures it is copied to `RUNTIME_QUEUE_DEAD_LETTER_STREAM`, acknowledged from the source stream, and its run becomes `failed` with `worker_retry_exhausted`. Queue enqueue failure returns HTTP `503` rather than silently running a supposedly durable task in the API process.

## Feedback Profile Loop

`POST /routes/feedback` now updates both the session and the user profile. Confirming a POI adds it to `liked_poi_ids`; rejecting it adds it to `avoided_poi_ids`. A route rating of 4 or 5 likes its stops, while 1 or 2 avoids them. The next retrieval filters avoided POIs and boosts liked POIs. POI-level feedback disables shared RouteBundle reuse for that request so personalized selection cannot be bypassed by a cross-user cached route.
