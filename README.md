# GenTrip

GenTrip 是一个面向城市本地出行的多轮路线规划 Agent。用户可以用自然语言描述区域、时间、预算、活动偏好和排除项，系统会检索 POI、生成并校验路线，并在后续对话中增删、替换或调整已有行程。

项目采用 Vue 3 + FastAPI + LangGraph，使用 PostgreSQL/PostGIS 保存业务数据和完成空间检索，使用 Redis 保存热状态并通过 Redis Streams 执行异步任务。DeepSeek 负责意图理解、路线评价和自然语言展示；时间、费用、营业状态与硬约束由确定性代码校验。Prometheus、OpenTelemetry、Tempo 和 Grafana 提供运行观测。

```text
Vue 3 -> FastAPI -> Redis Streams -> Plan Worker -> LangGraph
             |                              |
             +-> PostgreSQL/PostGIS         +-> DeepSeek / Tool adapters
             +-> Prometheus -> Tempo -> Grafana
```

## 本地启动

### 环境要求

- Docker Desktop，且 `docker version` 能连接 Docker daemon
- Node.js 22+，仅前端开发模式需要
- PowerShell 7 或 Windows PowerShell 5.1

### 1. 配置环境变量

```powershell
Copy-Item .env.example .env
```

系统默认关闭 LLM，仍可通过规则与模板完成规划。启用 DeepSeek 时，在本地 `.env` 中设置：

```dotenv
LLM_ENABLED=true
DEEPSEEK_API_KEY=replace-with-your-key
LLM_MODEL=deepseek-v4-pro
LLM_FAST_MODEL=deepseek-v4-flash
```

不要提交 `.env` 或任何真实密钥。

POI 数据源通过统一 Provider 切换。在线演示使用高德 Web 服务，开发测试可使用本地 PostGIS 或固定 Mock 数据：

```dotenv
POI_PROVIDER=amap
AMAP_API_KEY=replace-with-your-web-service-key
AMAP_CITY=上海
AMAP_POI_CACHE_TTL_SECONDS=900
```

`amap` 请求失败、超时或限流时会依次降级到 PostGIS 和 fixture；相同检索计划会缓存在 Redis 中。需要完全离线且结果可复现时使用 `POI_PROVIDER=mock`。

内部坐标统一使用 WGS-84（EPSG:4326）。约束解析会提取 `location_mentions`，地点解析按 `GazetteerGeoProvider -> AmapGeoProvider` 顺序执行：本地词典精确命中时直接返回，未命中才调用高德 place/geocode。高德边界负责 WGS-84 与 GCJ-02 双向转换，PostGIS、距离计算和路线生成始终只使用 WGS-84。

### 2. 一键启动

```powershell
.\scripts\start-local.ps1 -Build
```

使用 `postgis` 或需要为高德准备本地降级数据时，首次启动后导入仓库内的 POI fixture：

```powershell
docker compose exec api python scripts/import_poi_fixture.py
```

本地入口：

| 服务 | 地址 |
| --- | --- |
| Web | <http://127.0.0.1:5173> |
| API 文档 | <http://127.0.0.1:8080/docs> |
| 健康检查 | <http://127.0.0.1:8080/api/v1/health> |
| Grafana | <http://127.0.0.1:3000> |
| Prometheus | <http://127.0.0.1:9090> |

停止服务但保留数据库数据：

```powershell
.\scripts\stop-local.cmd
```

也可以只启动 Docker 服务，不启动 Vite 前端：

```powershell
docker compose up -d --build
docker compose ps
```

随后在另一个终端启动前端：

```powershell
Set-Location frontend
npm.cmd ci
npm.cmd run dev
```

## 单机服务器部署

当前仓库提供两种 Docker Compose 单机部署：

- `2 vCPU / 2 GB RAM / 40 GB`：个人演示配置，只运行前端、Caddy、API、单Worker、PostGIS和Redis；服务器必须配置4GB Swap。
- `4 vCPU / 8 GB RAM / 60 GB`：完整配置，额外长期运行Prometheus、OpenTelemetry、Tempo和Grafana。

### 1. 准备服务器

在 Ubuntu 22.04/24.04 上安装 Git、Docker Engine 和 Docker Compose Plugin，然后拉取项目：

```bash
git clone <your-repository-url> /opt/gentrip
cd /opt/gentrip
cp .env.example .env
```

修改 `.env`，至少替换以下配置：

```dotenv
POSTGRES_PASSWORD=replace-with-a-strong-password
AUTH_JWT_SECRET=replace-with-at-least-32-random-characters
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=replace-with-a-strong-password

# 首次启动设为 true；注册首个 owner 后立即改回 false。
PRODUCTION_ALLOW_REGISTRATION=true

# 免费域名示例：公网 IP 为 203.0.113.10
APP_DOMAIN=gentrip.203-0-113-10.sslip.io

LLM_ENABLED=true
DEEPSEEK_API_KEY=replace-with-your-key
```

`sslip.io` 会从域名中的数字解析公网 IP，无需注册账号。正式部署前确认云防火墙已开放 TCP `80/443`；Caddy 会自动申请并续期 HTTPS 证书。

如果服务器只有2GB内存，先配置4GB Swap：

```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### 2. 启动个人演示服务（2核2GB）

```bash
bash scripts/deploy-demo.sh
```

该脚本只启动 `postgres redis api worker frontend`，限制容器内存和规划并发，并幂等导入POI fixture。它不会启动完整观测栈。

### 3. 启动完整服务（4核8GB及以上）

```bash
docker compose -f docker-compose.yml -f docker-compose.production.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.production.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.production.yml ps
```

前端会在 Docker 构建阶段完成编译，并由 Caddy 提供静态文件、`/api` 反向代理和 SSE 转发。首次启动后导入 POI fixture：

```bash
docker compose exec api python scripts/import_poi_fixture.py
```

访问 `https://<APP_DOMAIN>` 注册第一个 owner。注册成功后将 `.env` 中的 `PRODUCTION_ALLOW_REGISTRATION` 改为 `false`，再应用配置：

```bash
docker compose -f docker-compose.yml -f docker-compose.production.yml up -d --build
```

宿主机上的 PostgreSQL、Redis、API、Prometheus、Tempo 和 Grafana 默认只绑定 `127.0.0.1`。公网防火墙只开放 `22`、`80` 和 `443`。

### 4. 验证部署

```bash
curl -fsS https://<APP_DOMAIN>/healthz
curl -fsS https://<APP_DOMAIN>/api/v1/health
docker compose -f docker-compose.yml -f docker-compose.production.yml ps
docker compose -f docker-compose.yml -f docker-compose.production.yml logs --tail=100 frontend api worker
```

健康检查应返回 `status=ok`，并确认 PostgreSQL 与 Redis 可用。还应在浏览器完成一次路线规划，验证 SSE 阶段事件和最终路线均能返回。

## 更新与备份

个人演示配置更新：

```bash
cd /opt/gentrip
git pull --ff-only
bash scripts/deploy-demo.sh
```

完整配置更新：

```bash
cd /opt/gentrip
git pull --ff-only
docker compose -f docker-compose.yml -f docker-compose.production.yml up -d --build
```

查看日志：

```bash
docker compose -f docker-compose.yml -f docker-compose.production.yml logs -f frontend api worker
```

停止服务但保留数据卷：

```bash
docker compose -f docker-compose.yml -f docker-compose.production.yml down
```

生产环境需要定期备份 PostgreSQL，并保留 Docker volumes 和受限权限的 `.env` 安全副本。不要执行 `docker compose down -v`，除非明确需要删除全部持久化数据。

## 更多文档

- [完整启动与部署说明](docs/startup-and-deployment.md)
- [Agent Runtime 设计](docs/agent-runtime-design.md)
- [运行时运维说明](docs/runtime-operations.md)
- [Golden Set 与质量评测](docs/golden-set.md)
