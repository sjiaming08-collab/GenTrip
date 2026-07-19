# GenTrip Backend

## 当前进度：P2 — 可持久化单 Agent 规划运行时

```
turn_orchestrate → constraint_extract → route_bundle_search
  → (hot: route_validate → bundle_rerank | cold: geo_resolve → poi_retrieve
  → route_generate → route_validate → route_evaluate → route_bundle_ingest)
  → route_present

Replan: replan_parse → lock_confirmed → partial_retrieval → local_optimize
  → validate_delta → render_diff
```

## 目录结构

```
backend/
├── fixtures/           # Mock 数据
├── tests/
└── src/
    ├── api/            # HTTP 路由与 DTO
    ├── graph/          # LangGraph State + 节点 + 图组装
    │   └── nodes/      # 冷路径六段节点
    ├── models/         # Pydantic 领域模型
    ├── mocks/          # Mock POI 等（Step A）
    ├── services/       # 业务编排
    ├── config.py
    └── main.py
```

## 本地运行

```bash
cd backend
pip install -e ".[dev]"
pytest -v
uvicorn src.main:app --reload --port 8000
curl http://localhost:8000/api/v1/health
curl -X POST http://localhost:8000/api/v1/routes/plan \
  -H "Content-Type: application/json" \
  -d '{"query":"徐汇逛吃"}'
```

## Multi-tenant login

Local development keeps the existing anonymous mode by default. To require an
authenticated workspace, set the following values before starting the API and
worker:

```bash
AUTH_ENABLED=true
AUTH_JWT_SECRET=<a-random-secret-at-least-32-characters>
AUTH_COOKIE_SECURE=true  # enable behind HTTPS
AUTH_ALLOW_REGISTRATION=false  # after the first workspace has been created
AUTH_LOGIN_RATE_LIMIT_ENABLED=true
AUTH_LOGIN_MAX_ATTEMPTS=5
AUTH_LOGIN_WINDOW_SECONDS=900
```

`POST /api/v1/auth/register` creates one user, one tenant, and an `owner`
membership. `POST /api/v1/auth/login` accepts credentials and sets the
`HttpOnly`, same-site `gentrip_access_token` cookie. API clients can instead
send `Authorization: Bearer <token>`. The browser UI uses the cookie so SSE
event streams keep the same identity without storing tokens in local storage.

Existing `X-API-Key` tenant mappings remain available for service-to-service
callers. Once `AUTH_ENABLED=true`, a request without a bearer token, login
cookie, or configured API key is rejected.

An `owner` can add an existing account with `POST /api/v1/tenants/current/members`,
change its role, remove it, and inspect `GET /api/v1/tenants/current/audit-events`.
Users can enumerate and switch assigned workspaces through `/auth/workspaces`
and `/auth/switch-workspace`. Login throttling uses Redis; with the limiter
enabled, unavailable Redis fails credential requests closed instead of silently
falling back to per-process counters.

Access tokens are bound to a server-side session. `POST /auth/logout` revokes
the current token immediately; `GET /auth/sessions`, `DELETE /auth/sessions/{id}`
and `POST /auth/sessions/revoke-others` provide device-session control. Apply
`migrations/008_auth_sessions.sql` before enabling this in a persistent setup.

## 当前能力

- Plan/Replan/Reject 单图编排，含自动放宽和可解释 diff
- Redis + Postgres 会话、运行、事件与 Redis Stream Worker
- RouteBundle 本地/Redis 两级缓存与结构化相似约束匹配
- 本地 PostGIS POI 导入脚本、营业时间校验和可降级交通适配层
- LLM token/phase telemetry、Prometheus 指标和可选 OpenTelemetry 导出
- Golden Set 与离线自然语言路线质量评测

## 仍依赖外部集成的能力

- 真实地图路径/实时交通与实时 POI/UGC 数据源
- 向量数据库或嵌入服务驱动的语义 RouteBundle 检索
- OTLP Collector、Postgres、Redis、Worker 的真实 Compose 运行验证

## Runtime smoke checks

`docker compose up --build` starts PostGIS, Redis, API, worker and Prometheus.
Prometheus loads `monitoring/alerts.yml`; the API exposes `/api/v1/metrics`.
Use `TRAVEL_TIME_PROVIDER=http` with a compatible `TRAVEL_TIME_HTTP_URL` only
when a routing service is available. It must return `distance_m` and
`duration_min`; timeout or invalid responses fall back to the deterministic
local estimate and are emitted in route telemetry as `fallback_used=true`.
