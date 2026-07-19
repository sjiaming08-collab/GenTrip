# Observability

`GET /api/v1/metrics` exposes Prometheus text metrics without request IDs, prompts, API keys, or raw user queries. The current metrics are plan run status/path, total plan duration, LLM token totals, and RouteBundle hit/miss totals.

When Docker is available, `docker compose up -d` starts Prometheus at `http://localhost:9090`. Its `gentrip-api` target scrapes the API on the internal Compose network every 15 seconds.

## Distributed tracing

GenTrip creates OpenTelemetry spans for incoming FastAPI requests, each `gentrip.plan_run`, and every DeepSeek JSON call. The async Redis Stream payload carries W3C `traceparent` and `tracestate`, so the worker run remains a child of the enqueueing HTTP request. Prompts, user queries, API keys, and LLM responses are deliberately excluded from span attributes.

Set `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` to an OTLP/HTTP trace endpoint, for example `http://localhost:4318/v1/traces`, to export spans. With the setting empty, spans and trace IDs are generated locally without an exporter. API response `meta.debug_trace_id` is the trace ID for correlating logs, traces, and a Plan Run.
