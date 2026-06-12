# 本地智能路线规划系统 (GenTrip / DeoReview)

## 项目概述

基于 **LLM + 检索增强 + 路线优化** 的本地出行智能规划系统。用户用自然语言描述出行目标，系统整合 POI 数据、UGC 评论与用户历史偏好，自动生成可执行的多站点路线方案，并在行程中支持动态调整。

**业务背景（赛题需求来源）：**

- 解决用户「多目的地串联、决策成本高」的痛点（时间 / 预算 / 排队 / 偏好等多目标权衡）
- 交付能力：**路线生成**（多 POI 连贯排程）+ **多条件个性化**（约束满足 + 历史偏好）

**系统设计原则：**

- **数据驱动规划，LLM 负责理解与解释，Optimizer 负责可行与高效**
- **同步 API 要短，重计算走异步 Worker**
- **POI + UGC + 用户画像** 与 **路线模板缓存** 分层，互不替代
- 按生产标准设计：**高并发、高可用、可观测、可降级、可演进**

---

## 目标架构（生产级分层）

```
┌─────────────────────────────────────────────────────────────────┐
│  客户端：Vue 3 H5 / Web                                          │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  接入层：CDN + WAF                                               │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  网关层：APISIX / Kong — 鉴权、限流、路由、灰度                  │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  同步业务层（高 QPS，无状态）                                     │
│  Route API · POI API · User Profile API                         │
│  职责：校验 → 写 task → 发 MQ → 立即返回 task_id + SSE URL       │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  异步编排层（长任务）                                             │
│  RocketMQ/Kafka → Plan Worker（LangGraph 执行器）                │
│  职责：意图解析 → 混合检索 → 分支生成 → 优化 → 校验 → 渲染       │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  AI 能力层                                                       │
│  LLM Gateway（路由/降级/计量）· Embedding Service · RAG         │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  数据层                                                          │
│  PostgreSQL · Elasticsearch · Milvus/pgvector · Redis · OSS     │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  平台层：OpenTelemetry · Prometheus/Grafana · Loki · Jaeger      │
│         Sentinel（熔断限流）· Nacos（配置中心）· K8s + ArgoCD     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 技术栈

### 应用与 AI

| 层级 | 选型 | 说明 |
|------|------|------|
| 语言 | Python 3.12 | AI 编排与业务 API |
| 同步 API | FastAPI | REST + SSE 流式进度 |
| 工作流引擎 | LangGraph | StateGraph + 条件分支 + 节点级 Trace |
| LLM 框架 | LangChain + langchain-openai | Structured Output |
| LLM | DeepSeek-V3（经 LLM Gateway） | 主模型 + 降级备用模型 |
| Embedding | BGE-small-zh-v1.5 + TEI 推理服务 | 独立部署，Worker 远程调用 |
| 异步任务 | RocketMQ/Kafka + Plan Worker | LangGraph 长流程削峰 |
| 前端 | Vue 3 (Vite + Composition API + Pinia) | |
| 地图 | 高德地图 API | 路径规划 / DeepLink，带熔断与缓存 |

### 数据与中间件

| 层级 | 选型 | 说明 |
|------|------|------|
| OLTP | PostgreSQL 16（主从） | 用户、路线、反馈、画像 |
| 全文 / UGC 检索 | Elasticsearch 8.x | POI / 评论 / 摘要检索 |
| 向量 | pgvector → Milvus | 早中期 pgvector，规模迁移 Milvus |
| 缓存 | Redis Cluster | 会话、热点模板、限流、Embedding 缓存 |
| 消息队列 | RocketMQ / Kafka | 规划任务、反馈异步、模板入库 |
| 对象存储 | OSS / S3 | 封面图、导出文件 |

### 网关、治理与可观测

| 层级 | 选型 | 说明 |
|------|------|------|
| API 网关 | APISIX / Kong | 鉴权 JWT、限流、路由 |
| 熔断限流 | Sentinel | LLM / 高德 / ES 依赖保护 |
| 配置中心 | Nacos / Apollo | Prompt、阈值、Feature Flag |
| 指标 | Prometheus + Grafana | QPS、P99、Token、队列积压 |
| 日志 | Loki / ELK | 结构化 JSON，含 trace_id / task_id |
| 链路追踪 | OpenTelemetry + Jaeger | 网关 → API → MQ → Worker → LLM → DB |
| 部署 | Docker + Kubernetes + ArgoCD | 多副本 HPA、蓝绿/金丝雀 |

---

## 知识分层

| 层级 | 内容 | 作用 |
|------|------|------|
| **L1 领域知识** | POI 库 + UGC 摘要库 | 稳定可 RAG，支撑选点依据 |
| **L2 路线模板** | RouteTemplate（pgvector 语义检索） | 高频场景骨架复用，加速响应 |
| **L3 会话记忆** | 当次 GraphState + 用户反馈 | 动态调整与个性化微调 |

检索顺序：**L1 定候选 → L2 定骨架 → L3 定微调**

---

## 核心规划流程

### 生产请求链路

```
1. POST /api/v1/routes/plan
   Gateway 鉴权限流 → Route API 校验 → 写 Redis task → 发 MQ
   → 立即返回 { task_id, sse_url }（目标 P99 < 200ms）

2. Plan Worker 消费 MQ，执行 LangGraph
   → 阶段性结果写 Redis → SSE 推送进度

3. GET /api/v1/routes/stream/{task_id}
   SSE：intent → retrieve → generate → optimize → validate → done

4. POST /api/v1/routes/{route_id}/feedback
   → 写 PG + 发 MQ → 异步更新模板评分 & 用户画像
```

### LangGraph 节点流水线

```
用户 NL 输入 + user_id + 经纬度
     │
     ▼
[1] intent_parse          — LLM 解析 → RouteIntent（结构化约束 + 隐式偏好）
     │
     ▼
[2] constraint_check      — 约束冲突检测；必要时澄清或多方案（Plan A / Plan B）
     │
     ▼
[3] hybrid_retrieval      — L1：POI 结构化 + 向量检索；UGC 评论/摘要 RAG
     │                       L2：pgvector 检索 Top-K RouteTemplate
     ▼
[4] poi_rank              — 多维打分（相关性 / 品质 / 个性化 / 拥挤 / 距离）
     │
     ▼
[5] match_score           — 模板匹配分（语义 + 区域 + 时长 + 预算 + 品类）
     │
     ├── score ≥ 0.90  → [6a] cache_hit       — 零 LLM 直出（约束完全一致）
     ├── 0.75–0.90     → [6b] adapt_template — LLM 轻量适配 (~800ms)
     └── score < 0.75  → [6c] full_generate  — LLM 完整生成 (~5s)
     │                                    └→ 质量门禁 → 异步入库模板
     ▼
[7] route_optimizer       — 顺序 / 时间窗 / 营业时段 / 路程可行性（独立 CPU 模块）
     │
     ▼
[8] constraint_validator  — 可行性校验；冲突时标注 relaxed_constraints
     │
     ▼
[9] render_output         — 结构化输出 + UGC 依据 + 地图 DeepLink + SSE 推送
     │
     ▼
[10] feedback（异步）     — 更新 L2 模板评分 & L3 用户画像；低分模板淘汰
```

**职责分工：**

- **Optimizer**：路线顺序、时间轴、约束可行性
- **LLM**：意图理解、模板适配、叙事文案、权衡解释
- **UGC RAG**：每站 `ai_tip` 与选点理由必须 grounded，附 1–2 条评论依据

### 动态调整（Replan 模式）

支持行程中增量修订，不重新跑全流程：

- 输入：已确认站点、剩余时间、新约束（跳过 / 加站 / 迟到）
- `GraphState.session_context` 保存会话进度
- 触发 `replan` 分支：在剩余 POI 候选上局部重优化

---

## 核心数据模型

| 模型 | 说明 |
|------|------|
| `RouteIntent` | 出行目的 + `RouteConstraints` + `InferredPreferences` |
| `RouteConstraints` | 时间 / 区域 / 预算 / 品类 / 排队容忍（null = 未指定） |
| `PoiEntity` / `ScoredPoi` | POI 实体 + 多维综合评分 |
| `RoutePlan` / `ItineraryStop` | 完整路线 + 每站时间 / 排队预估 / UGC 贴士 |
| `RouteTemplate` | L2 模板（语义向量 + route_json + 质量指标） |
| `RouteFeedback` | 用户评分 → 双写模板质量与用户画像 |
| `GraphState` | LangGraph 节点间状态契约 |

---

## 抽象接口与目录结构

```
backend/src/
├── abstracts/
│   ├── embedder.py           — 向量编码器
│   ├── vector_store.py       — 向量存储
│   ├── poi_repository.py     — POI 结构化 + 向量检索 + rank
│   ├── ugc_repository.py     — UGC 评论/摘要检索（待实现）
│   ├── user_profile_repo.py  — 用户画像读写（待实现）
│   ├── template_repo.py      — 路线模板仓库
│   └── llm_client.py         — LLM 调用（经 Gateway）
├── graph/
│   ├── state.py              — GraphState 契约
│   ├── router.py             — StateGraph 组装
│   └── nodes/                — 各节点实现
├── models/                   — Pydantic 数据模型
├── tools/                    — POI 搜索 / 距离估算 / 天气
├── db/                       — PostgreSQL / Redis / Vector 实现
└── main.py                   — FastAPI 入口
```

---

## 可靠性设计

### SLO 目标（示例）

| 接口 | 可用性 | 延迟 |
|------|--------|------|
| 提交规划任务 | 99.9% | P99 < 200ms |
| SSE 首包 | 99.5% | < 1s |
| 完整路线生成 | 99% | P95 < 8s（全量分支） |
| POI 搜索 | 99.9% | P99 < 100ms |

### 治理策略

| 策略 | 说明 |
|------|------|
| 超时级联 | 每层明确 deadline；Graph 总超时 > 各节点之和 |
| 熔断 | Sentinel 保护 LLM、高德、ES 依赖 |
| 舱壁隔离 | 适配分支与全量分支 Worker 池分离 |
| 幂等 | `Idempotency-Key` 防重复提交 |
| 降级链 | LLM 超时 → 高匹配模板直出 → 规则 POI 组合 |
| 模板质量门禁 | 异步入库前校验约束满足度与 POI 有效性 |
| 健康检查 | K8s liveness/readiness + 依赖探测 |

### LLM 调用策略

```
超时（适配 3s / 全量 8s）
  → 重试 1 次
  → 降级模型 / 模板直出
  → 返回部分结果 + 稍后重试提示
```

---

## 可观测性

**标准：OpenTelemetry，Metrics + Logs + Traces 三件套**

LangGraph 节点级 Span 示例：

```
trace: plan_route
├── span: intent_parse       (llm.latency, tokens)
├── span: hybrid_retrieval   (poi.count, ugc.count, vector.latency)
├── span: match_score
├── span: full_generate
│   ├── span: poi_retrieval
│   ├── span: ugc_retrieval
│   └── span: route_optimizer
├── span: constraint_validator
└── span: render_output
```

日志必含字段：`trace_id`、`task_id`、`user_id`、`graph_node`、耗时、错误码。

---

## 赛题能力映射

| 赛题要求 | 系统模块 | 生产要点 |
|---------|---------|---------|
| POI 数据 | POI Service + PG + ES | 双写/CDC、缓存、只读副本 |
| UGC | UGC Repository + ES RAG | 索引分片、检索超时降级 |
| 个性化 | User Profile Service | Redis 热读 + MQ 异步画像更新 |
| 路线生成 | Plan Worker + LangGraph + Optimizer | 队列削峰、LLM 降级 |
| 动态调整 | Replan API + session_context | Redis 会话状态、局部重算 |
| 多条件权衡 | Constraint Validator + 多方案输出 | Plan A / Plan B 显式 trade-off |

---

## 演进路线

| 阶段 | 目标 | 范围 |
|------|------|------|
| **P0 可演示** | 赛题功能闭环 | 单体 FastAPI + LangGraph + PG + Redis + 基础日志 |
| **P1 可上线** | 异步化 + 基础监控 | + MQ + Worker + Prometheus + OTel + 网关限流 |
| **P2 可扩容** | 检索与 AI 分离 | + ES + UGC RAG + Embedding 服务 + LLM Gateway + 读写分离 |
| **P3 生产级** | 高可用 + 全链路 | + K8s 多 AZ + Sentinel + Jaeger + 降级体系 + 压测基线 |

代码结构按 P3 边界组织（包名、接口），部署按阶段渐进，避免过早微服务拆分。

---

## 执行计划

| Step | 内容 | 状态 |
|------|------|------|
| 1 | 抽象接口层（ABC 解耦） | ✅ |
| 2 | 数据模型（RouteIntent / RoutePlan / RouteTemplate 等） | ✅ |
| 3 | LangGraph 节点实现（含 Optimizer / Validator / UGC 检索） | 进行中 |
| 4 | DB / 基础设施（PG + pgvector + Redis + ES） | 待开始 |
| 5 | 异步任务链路（MQ + Worker + SSE） | 待开始 |
| 6 | FastAPI 路由 + LLM Gateway | 待开始 |
| 7 | Vue 3 前端 + 高德地图 | 待开始 |
| 8 | 可观测接入（OTel + Prometheus + 结构化日志） | 待开始 |
| 9 | 端到端测试（5 个真实场景 + 压测基线） | 待开始 |

---

## API 端点（规划）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/routes/plan` | 提交规划任务，返回 task_id |
| GET | `/api/v1/routes/stream/{task_id}` | SSE 流式进度与结果 |
| GET | `/api/v1/routes/{route_id}` | 查询历史路线 |
| POST | `/api/v1/routes/{route_id}/feedback` | 提交反馈（异步处理） |
| POST | `/api/v1/routes/{route_id}/replan` | 行程中动态调整 |
| GET | `/api/v1/poi/search` | POI 直搜（不生成路线） |
| GET | `/api/v1/health` | 健康检查 |
