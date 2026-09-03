# GenTrip 启动与部署指南

本文档基于当前仓库的实际配置，说明如何在 Windows 本地运行、以开发模式调试，以及使用 Docker Compose 做单机生产部署。

## 1. 运行结构

GenTrip 由以下组件组成：

| 组件 | 默认端口 | 作用 |
| --- | ---: | --- |
| FastAPI API | `8080` | HTTP API、SSE、认证、健康检查和指标 |
| Agent worker | 无宿主机端口 | 从 Redis Stream 消费规划任务并运行 LangGraph |
| PostgreSQL + PostGIS | `5432` | 会话、用户、runs、checkpoints、审计和 POI 持久化 |
| Redis | `6379` | 热缓存、RouteBundle、任务队列、pending 消息和 DLQ |
| Vue 前端 | `5173` | 本地开发页面；不包含在 Compose 中 |
| Prometheus | `9090` | 指标采集和告警规则 |
| Grafana | `3000` | 指标与 Trace 面板 |
| Tempo | `3200` | OpenTelemetry Trace 存储 |

API 和 worker 启动时会按文件名顺序执行 `backend/migrations/*.sql`。迁移脚本必须保持幂等。

## 2. 前置条件

本地一键运行需要：

- Windows 10/11 或 Linux
- Docker Desktop，并启用 Linux containers
- Docker Compose v2
- Node.js 22+ 和 npm，用于运行前端
- 可选：Python 3.12，用于本机测试和评测

Windows PowerShell 中先验证 Docker：

```powershell
docker version
docker compose version
```

如果 `docker` 无法识别，重启终端并确认 Docker Desktop 安装目录已经加入 `PATH`。如果能识别命令但无法连接 `docker_engine`，先启动 Docker Desktop，等状态变为 Running。

## 3. 本地一键启动（推荐）

以下命令均在仓库根目录执行：

Windows 下推荐直接使用启动脚本：

```powershell
Set-Location C:\Users\night\agent\GenTrip
.\scripts\start-local.ps1
```

首次构建或后端依赖发生变化时：

```powershell
.\scripts\start-local.ps1 -Build
```

脚本会检查 Docker、创建缺失的 `.env`、启动 Compose、等待 API/Postgres/Redis 健康，并在后台启动前端。前端日志写入 `.runtime_logs/`。停止时执行：

```powershell
.\scripts\stop-local.cmd
```

默认会在 5 秒退出窗口内停止前端和全部 Compose 服务，保留容器和 Docker volumes，下一次启动无需重新创建容器。常用停止模式如下：

```powershell
# 只停止前端、API 和 Worker，保留 PostgreSQL、Redis 与观测服务
.\scripts\stop-local.cmd -AppsOnly

# 停止服务并移除容器，仍然保留数据库等 volumes
.\scripts\stop-local.cmd -RemoveContainers

# 服务无法正常退出时紧急终止，不建议作为日常操作
.\scripts\stop-local.cmd -Force
```

只启动后端或调整 Worker 数量时可使用：

```powershell
.\scripts\start-local.ps1 -SkipFrontend -WorkerReplicas 3
```

等价的手动启动命令如下：

```powershell
Set-Location C:\Users\night\agent\GenTrip
Copy-Item .env.example .env -ErrorAction SilentlyContinue
docker compose up -d --build
docker compose ps
```

本地 Compose 会启动 PostGIS、Redis、API、worker、Prometheus、Tempo 和 Grafana。`.env.example` 默认关闭 LLM，因此没有模型密钥也能使用规则和模板完成规划。

首次启动后导入本地 POI fixture：

```powershell
docker compose exec api python scripts/import_poi_fixture.py
```

导入脚本可重复执行。完成后验证服务：

```powershell
Invoke-RestMethod http://localhost:8080/api/v1/health
Invoke-WebRequest -UseBasicParsing http://localhost:8080/api/v1/metrics
```

健康响应应满足：

- `status` 为 `ok`
- `dependencies.database` 为 `true`
- `dependencies.redis` 为 `true`
- `runtime_mode` 为 `persistent`

常用地址：

- API 文档：<http://localhost:8080/docs>
- API 健康检查：<http://localhost:8080/api/v1/health>
- Prometheus：<http://localhost:9090>
- Grafana：<http://localhost:3000>，本地默认账号为 `admin/admin`
- Tempo readiness：<http://localhost:3200/ready>

## 4. 启动前端

Compose 当前不负责运行前端。本地开发时打开第二个 PowerShell：

```powershell
Set-Location C:\Users\night\agent\GenTrip\frontend
npm.cmd install
npm.cmd run dev
```

浏览器访问 <http://localhost:5173>。Vite 仅在开发模式下把 `/api` 代理到 `http://localhost:8080`。

验证生产构建：

```powershell
npm.cmd run build
```

构建结果位于 `frontend/dist/`。

## 5. 启用 DeepSeek

只修改本地 `.env`，不要把密钥提交到 Git：

```dotenv
LLM_ENABLED=true
DEEPSEEK_API_KEY=replace-with-your-key
LLM_MODEL=deepseek-v4-pro
LLM_FAST_MODEL=deepseek-v4-flash
LLM_DISABLE_THINKING=true
LLM_FAST_TIMEOUT_SEC=12
LLM_ROUTE_EVALUATE_TIMEOUT_SEC=15
ROUTE_EVALUATE_MODE=llm_with_fallback
SESSION_SUMMARY_MODE=async_llm
```

更新配置后重建 API 和 worker：

```powershell
docker compose up -d --build api worker
docker compose logs -f api worker
```

日志中可以出现模型名、调用状态、耗时和 token，但不应出现 API key 或完整 prompt。

## 6. 调用 Agent

本地默认关闭认证并允许匿名 workspace，可以直接调用同步接口：

```powershell
$body = @{
  query = "黄浦区下午玩五个小时，不去博物馆，想吃日料"
  user_id = "local-traveler"
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:8080/api/v1/routes/plan `
  -ContentType "application/json" `
  -Body $body
```

前端主要使用异步运行接口：

```text
POST /api/v1/routes/plan/runs
GET  /api/v1/routes/plan/runs/{run_id}
GET  /api/v1/routes/plan/runs/{run_id}/events
GET  /api/v1/routes/plan/runs/{run_id}/checkpoints
POST /api/v1/routes/plan/runs/{run_id}/cancel
```

客户端重试时应复用同一个 `idempotency_key`。幂等键按 tenant 隔离，首次请求尚未获得 `session_id` 时也能返回原来的 run。

## 7. 开发模式启动后端

需要调试 Python 源码时，可以只用 Docker 启动依赖，在本机运行 API。先停止 Compose 中的 API 和 worker，避免端口及任务重复消费：

```powershell
docker compose stop api worker
docker compose up -d postgres redis tempo otel-collector prometheus grafana
```

安装后端：

```powershell
$python = "D:\conda3\envs\GenTrip\python.exe"
& $python -m pip install -e ".\backend[dev]"
```

确保 `.env` 中本机连接地址为：

```dotenv
DATABASE_URL=postgresql://gentrip:gentrip@127.0.0.1:5432/gentrip
REDIS_URL=redis://127.0.0.1:6379/0
RUNTIME_EXECUTION_MODE=redis_stream
```

分别打开两个终端：

```powershell
Set-Location C:\Users\night\agent\GenTrip\backend
& "D:\conda3\envs\GenTrip\python.exe" -m uvicorn src.main:app --host 0.0.0.0 --port 8080 --reload
```

```powershell
Set-Location C:\Users\night\agent\GenTrip\backend
& "D:\conda3\envs\GenTrip\python.exe" -m src.worker
```

如果不希望启动 worker，可将 `RUNTIME_EXECUTION_MODE` 改为 `inprocess`。此模式适合本地调试，不应用于多实例部署。

## 8. 单机生产部署

当前仓库提供的是 Docker Compose 单机部署，不是 Kubernetes 多副本部署。生产环境至少需要：

- 一台安装 Docker Engine/Compose 的服务器
- HTTPS 域名和反向代理
- 强 PostgreSQL 密码
- 至少 32 字符的 JWT secret
- 非默认 Grafana 管理员密码
- 持久化 Docker volumes 和定期备份

在服务器创建 `.env`，至少修改：

```dotenv
POSTGRES_PASSWORD=replace-with-a-strong-password
AUTH_JWT_SECRET=replace-with-at-least-32-random-characters
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=replace-with-a-strong-password
LLM_ENABLED=true
DEEPSEEK_API_KEY=replace-with-your-key
LLM_MODEL=deepseek-v4-pro
LLM_FAST_MODEL=deepseek-v4-flash
LLM_DISABLE_THINKING=true
ROUTE_EVALUATE_MODE=llm_with_fallback
SESSION_SUMMARY_MODE=async_llm
```

不要在命令行参数、Git、镜像或日志中保存真实密钥。推荐由服务器 secret manager 或受限权限的 `.env` 注入。

检查最终配置，再启动 production override：

```powershell
docker compose -f docker-compose.yml -f docker-compose.production.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.production.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.production.yml ps
```

production override 会：

- 启用 JWT 认证
- 禁止客户端自行指定 tenant
- 关闭公开注册
- 启用 Secure Cookie
- 启用登录限流

因此生产前必须解决以下两项：

1. **HTTPS**：Secure Cookie 只会通过 HTTPS 发送。反向代理应终止 TLS，并把 `/api` 转发到 API 的 `8080` 端口。
2. **首个管理员账号**：production override 默认禁止注册。可以在仅管理员可访问的初始化窗口中，使用基础 Compose 临时设置 `AUTH_ENABLED=true`、`AUTH_ALLOW_REGISTRATION=true` 创建首个 owner，然后关闭注册并切换到 production override。不要把公开注册长期暴露到互联网。

### 前端生产发布

```powershell
Set-Location frontend
npm.cmd ci
npm.cmd run build
```

将 `frontend/dist/` 部署到 Nginx、Caddy 或对象存储。当前前端固定访问同源 `/api/v1`，因此推荐：

- `/` 提供 `frontend/dist` 静态文件
- `/api/` 反向代理到 `http://api:8080` 或服务器上的 `127.0.0.1:8080`
- SPA 未命中文件时回退到 `index.html`
- SSE 路径关闭代理缓冲并延长读取超时

不要把 PostgreSQL、Redis、Prometheus、Tempo 和 API 的内部端口直接暴露到公网。公网通常只开放反向代理的 `80/443`。

## 9. 日志与观测

查看所有服务状态和近期日志：

```powershell
docker compose ps
docker compose logs --tail 200 api worker postgres redis
docker compose logs -f api worker
```

每个 run 的 API 返回和持久化结果包含：

- `phase_log`：执行节点、状态和摘要
- `llm_calls`：模型、状态、耗时和 token
- `tool_calls`：工具来源、状态和降级信息
- `debug_trace_id`：Trace/run 关联标识

worker 重试耗尽后，消息会进入 Redis DLQ。相关接口：

```text
GET  /api/v1/runtime/dlq
POST /api/v1/runtime/dlq/{message_id}/replay
```

详细运行时操作见 [runtime-operations.md](runtime-operations.md)。

## 10. 数据、停止与备份

普通停止不会删除数据：

```powershell
docker compose down
```

重新启动：

```powershell
docker compose up -d
```

以下命令会永久删除 PostgreSQL、Redis、Prometheus、Tempo 和 Grafana volumes，除非明确需要全量重置，否则不要执行：

```powershell
docker compose down -v
```

备份 PostgreSQL：

```powershell
New-Item -ItemType Directory -Force backups | Out-Null
docker compose exec -T postgres pg_dump -U gentrip -d gentrip -Fc -f /tmp/gentrip.dump
docker compose cp postgres:/tmp/gentrip.dump .\backups\gentrip.dump
```

生产环境应额外备份 Docker volume、`.env` 的安全副本和反向代理配置，并定期做恢复演练。

## 11. 测试与发布前检查

后端测试：

```powershell
D:\conda3\envs\GenTrip\python.exe -m pytest backend\tests -m "not runtime_integration" -q
```

路线质量门禁：

```powershell
D:\conda3\envs\GenTrip\python.exe scripts\evaluate_route_plans.py `
  --json-output .runtime_logs\quality-gate.json
D:\conda3\envs\GenTrip\python.exe scripts\evaluate_route_plans.py `
  --blueprint-enabled `
  --json-output .runtime_logs\quality-gate-blueprint.json
```

灰度启用 Planner V3 冷路径时，在 `.env` 中设置：

```dotenv
PLANNER_BLUEPRINT_ENABLED=true
CONSTRAINT_COMPILER_ENABLED=true
BLUEPRINT_FEASIBILITY_ENABLED=true
JOINT_ROUTE_SOLVER_ENABLED=true
FAILURE_DIRECTED_REPAIR_ENABLED=true
```

仅关闭 `PLANNER_BLUEPRINT_ENABLED` 即可回退到原 `domains → route skeletons` 生成链路，其余开关保持独立可回滚。

前端和 Compose 检查：

```powershell
Set-Location frontend
npm.cmd run build
Set-Location ..
docker compose config --quiet
```

发布前还应验证：

- `/api/v1/health` 返回 PostgreSQL 和 Redis 正常
- `/api/v1/metrics` 返回 HTTP 200
- API 和 worker 日志无 migration、认证或 Redis consumer group 错误
- 一次异步规划能从 queued 进入 completed/degraded
- SSE 能持续输出节点进度
- 生产 HTTPS 下登录 Cookie 能正常回传

## 12. 常见故障

### `docker` 无法识别

关闭并重新打开 PowerShell，确认 Docker Desktop 已安装，并检查：

```powershell
Get-Command docker
```

### `permission denied ... docker_engine`

Docker Desktop 尚未启动、当前用户无 named pipe 权限，或命令运行在受限沙箱。先在普通本机终端执行 `docker version` 区分 daemon 故障和终端权限问题。

### 前端出现 `ECONNREFUSED /api/v1/health`

Vite 正常运行但 API 的 `8080` 端口不可访问。检查：

```powershell
docker compose ps api
docker compose logs --tail 100 api
Invoke-RestMethod http://localhost:8080/api/v1/health
```

### 请求返回 `401`

当前运行配置启用了 `AUTH_ENABLED=true`。先通过 `/api/v1/auth/login` 登录，或在非生产本地环境关闭认证后重启 API。不要通过伪造 `tenant_id` 绕过认证。

### 规划一直停留在 queued

worker 没有消费 Redis Stream。检查 worker、Redis 和 consumer group：

```powershell
docker compose ps worker redis
docker compose logs --tail 200 worker redis
```

### 修改 `.env` 后没有生效

环境变量在容器创建时注入。重新创建相关容器：

```powershell
docker compose up -d --force-recreate api worker
```

代码或依赖发生变化时使用 `--build`。
