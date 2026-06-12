# 本地智能路线规划系统 (DeoReview)

## 项目概述

基于 LangGraph + LLM 的智能路线规划系统。用户用自然语言输入出行需求，系统自动生成个性化 POI 路线方案。

**核心流程：先检索知识库，再决定走轻量适配还是完整生成，最后根据用户反馈更新知识库。**

---

## 技术栈

| 层级 | 选择 |
|------|------|
| 语言 | Python 3.12 |
| 工作流引擎 | LangGraph (StateGraph + 条件分支) |
| LLM 框架 | LangChain + langchain-openai |
| LLM | DeepSeek-V3 (OpenAI-compatible) |
| Embedding | BGE-small-zh-v1.5 (sentence-transformers, 本地) |
| 数据库 | PostgreSQL 16 + pgvector |
| 缓存 | Redis |
| API 框架 | FastAPI (SSE 流式) |
| 前端 | Vue 3 (Vite + Composition API) |
| 地图 | 高德地图 API |

---

## 核心流程（两分支）

```
用户 NL 输入
     │
     ▼
[1] intent_parse      — LLM 解析意图 → RouteIntent（结构化约束）
     │
     ▼
[2] search_cache      — pgvector 语义检索知识库 → Top-5 RouteTemplate
     │
     ▼
[3] match_score       — 计算最佳匹配的 matchScore
     │
     ├── matchScore ≥ 0.75 → [4a] adapt_template  — LLM 轻量适配 (~800ms)
     │
     └── matchScore < 0.75 → [4b] full_generate   — LLM 完整生成 (~5s)
     │                              └→ asyncSaveAsTemplate (异步入库)
     ▼
[5] render_output     — 结构化输出 + 地图 DeepLink + SSE 推送
     │
     ▼
[6] feedback          — 用户反馈 → 更新模板评分 / 淘汰低分模板
```

---

## 抽象接口清单

```
backend/src/
├── abstracts/
│   ├── __init__.py
│   ├── embedder.py       — 向量编码器抽象
│   ├── vector_store.py   — 向量存储抽象
│   ├── poi_repository.py — POI 数据仓库抽象
│   ├── template_repo.py  — 路线模板仓库抽象
│   └── llm_client.py     — LLM 调用客户端抽象
├── graph/
│   ├── state.py          — GraphState 契约 (TypedDict)
│   └── nodes/            — LangGraph 节点函数签名
├── models/               — Pydantic 数据模型 (已完成)
└── ...
```

---

## 执行计划

### Step 1: 抽象接口层 ✅ 当前
定义所有模块的抽象基类 (ABC)，确保各层之间通过接口解耦。

### Step 2: 数据模型
Pydantic models — RouteIntent, RouteConstraints, PoiEntity, RoutePlan, RouteTemplate 等。

### Step 3: LangGraph 节点实现
基于抽象接口实现各节点：intent_parse, search_cache, match_score, adapt_template, full_generate, render_output, feedback。

### Step 4: DB / 基础设施实现
PostgreSQL + pgvector + Redis 的具体实现类。

### Step 5: FastAPI 路由
REST API + SSE streaming 端点。

### Step 6: Vue 3 前端
Vite 项目 + 组件开发 + API 对接。

### Step 7: 测试与验证
5 个真实场景端到端测试。
