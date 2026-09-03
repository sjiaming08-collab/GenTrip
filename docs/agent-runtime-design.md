# GenTrip Agent 运行时设计

> 本文档只讨论 **Agent 运行时行为**：主循环、编排、工具、提示词、会话记忆、状态共建与回复机制。  
> 不涉及数据库选型、部署、网关、监控等工程实现。

---

## 0. 当前实现阶段（2026-09-02）

当前代码已进入 **Planner V3**。LLM 只提取当前 query 的显式语义并构思活动蓝图；`constraint_compile` 将事实统一编译为 Hard、Soft、Policy，默认值、记忆合并、时间窗口、POI、营业状态、交通和预算判断均由确定性节点负责。冷路径为：`constraint_extract → constraint_compile → planning_decision → route_bundle_search → geo_resolve → activity_blueprint → blueprint_compile → poi_retrieve → route_generate → route_validate → route_evaluate → route_bundle_ingest → route_present`。Bundle 命中仍跳过蓝图与检索。

`full_day` 是符号时间语义，不再等同于固定 480 分钟。默认 envelope 为最少 420、目标 540、最多 600 分钟，09:30 最早开始、20:30 最晚结束；这些是可撤销 Policy，不覆盖用户明确时间。Blueprint 在检索前按乐观/期望/保守时长预检，优先重排 flexible 活动绕开餐饮窗口，再删除冲突的 optional/policy 槽位。路线生成使用绝对时间 Beam Search，并在扩展候选时联合检查营业、交通、预算和总时长。

地点约束不再由 `constraint_extract` 硬输出固定 `district`。当前链路是：显式地点/城市/地址或浏览器坐标 → `GeoResolver` → WGS-84 `GeoScope` → 高德周边检索或 PostGIS 半径过滤。`city`、`district` 是可选提示字段，任意行政区均可进入解析；显式地点优先于当前位置，当前位置优先于默认上海全市范围。
## 1. 设计目标与边界

GenTrip 是 **单 Agent、推荐优先** 的本地出行规划系统：

- **一个 LangGraph Agent** 负责 Plan Run：**约束提取 → 地点解析 → POI 检索 → 多候选路线 → 校验 → 评估 → Top-K 输出**；P1 先稳定 GeoScope 冷路径，P2 再接入 RouteBundle 热路径。
- 用户输入模糊问题时优先用可见假设直接推荐；只有缺少无法安全推断的关键前提时才返回结构化澄清。
- 用户往往 **不知道自己具体要什么**——系统的职责是 **主动推荐**，而不是收集完整表单后再规划。
- 路线输出后，用户可通过自然语言 **修订**（换店、跳过、加站）；Agent 在已有上下文上增量 Replan，而非每轮从零开始。
- 所有 LLM 输出必须 **结构化**（意图、路线、假设说明），便于校验、展示与后续 Replan。

### 1.1 核心设计原则：推荐优先、可行性优先

| 原则 | 含义 |
|------|------|
| **Default Before Clarify** | 预算、时长、人数等可安全补全项优先推断并写入 assumptions |
| **Truthful Outcome** | 每条出行输入都执行 Plan/Replan，但只有通过硬约束校验的路线才能提交 |
| **Assumption First** | 推断出的默认值、画像补全、场景模板必须写入 `assumptions[]`，对用户可见 |
| **Recommend, Don't Ask** | 约束冲突时不追问，而是自动放宽或返回 **Top-K 条评估最高的路线** |
| **Geo First, Hot Later** | P1 先用 GeoScope 稳定地点解析与 POI 召回；P2 再用线下 RouteBundle 跳过全量生成/评估 |
| **Single Agent** | 一个 StateGraph + 一份 GraphState；节点是流水线步骤，不是多个独立 Agent |

### 1.2 Agent 运行时模式（仅两种主模式）

| 模式 | 触发 | 目标 |
|------|------|------|
| **Plan** | 用户首次输入、或要求「重新规划」 | 从模糊/不完整输入 → **直接输出推荐路线** |
| **Replan** | 已有路线上的修订（换店、跳过、加站、改偏好） | 锁定已确认段，局部重算并输出 diff |

**非出行闲聊**（如「今天股票怎么样」）→ 简短 **RejectReply**，引导回出行场景；仍不进入澄清式盘问。

---

## 2. 运行时主循环

### 2.1 主循环形态

```
┌─────────────────────────────────────────────────────────────┐
│                     RUNTIME MAIN LOOP                        │
│                     （单 Agent）                              │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
  [1] 接收用户输入（文本 ± 位置 ± 会话 ID）
        │
        ▼
  [2] 加载会话状态（Working Memory + User Profile + 当前路线）
        │
        ▼
  [3] 意图增量解析（merge，非覆盖）
        │
        ▼
  [4] 路由决策：Plan │ Replan │ Reject
        │
        ├── Plan ──► 约束提取 → Bundle检索? → POI → 多路线 → 校验 → 评估 → Top-K
        │
        └── Replan ──► 锁定已确认段 → 局部重算 → 输出 diff
        │
        ▼
  [5] 用户新输入（修订 / 新需求）──► 回到 [1]
```

**关键变化：** 澄清不再是默认对话模式；运行结果显式区分 `route_ready / clarification_required / infeasible / change_applied / change_rejected`。

### 2.2 单轮内 vs 跨轮

| 概念 | 含义 |
|------|------|
| **Turn（对话轮）** | 用户发一条消息 → Agent 回复一次 |
| **Run（规划运行）** | 一次 Plan/Replan 内部的多节点执行；**首条输入也必须有 Run** |
| **Session（会话）** | 多 Turn 共享 `session_id`；用于 Replan 与偏好累积，**不用于澄清盘问** |

### 2.3 缺失约束如何补全（代替 Clarify）

当 `RouteIntent` 中字段为 null 时，按优先级 **自动补全**，并记录为 `Assumption`：

| 优先级 | 来源 | 示例 |
|--------|------|------|
| 1 | 用户本轮显式表述 | 「200 以内」→ budget=200 |
| 2 | 用户当前位置 | 无区域 → 以 `user_lat/lng` 反查区县 |
| 3 | 会话内历史 | 上一轮说过「3 小时」→ 沿用 |
| 4 | User Profile | 常去徐汇、偏爱日料、人均 150 |
| 5 | 场景默认模板 | 逛吃：默认 3h / 人均 150 / 3 站；亲子：默认 5h / 2 站 |

显式语义在 **`constraint_extract`** 提取，补全与分级在 **`constraint_compile`** 完成，输出兼容 `Constraints`、V3 `CompiledConstraints` 与 `assumptions[]`。只有地点或可用时间等关键前提无法安全推断时，`planning_decision` 才返回结构化澄清。
支持 **`return_by`（几点回家）** 与 **`time_budget_minutes`** 并存或二选一。

### 2.4 运行时优先级

1. **安全与可行性**（营业、预算、时间、排除项不满足时不得伪造成功路线）
2. **推荐优先**（可安全推断时带 assumptions 直接规划）
3. **用户本轮显式指令**（「不要火锅」覆盖画像默认）
4. **已确认路线段**（Replan 时不可擅自改动）
5. **User Profile 与场景默认**（推荐依据，须在 UI 展示）

---

## 3. 编排设计（单 Agent 两层）

### 3.1 两层编排

```
Turn Orchestrator（对话级）
    │  决定：Plan / Replan / Reject
    ▼
Run Orchestrator（规划级）
    │  决定：走哪条生成路径、调用哪些工具
    ▼
Node Pipeline（节点流水线，同一 StateGraph 内）
```

**Turn Orchestrator** 输入：用户 utterance + 会话快照。  
输出：`turn_mode` + 更新后的 `RouteIntent` 草案。

**判断逻辑（简化）：**

- 无 `current_route` 或用户说「重新规划」→ **Plan**
- 有 `current_route` 且 utterance 含修订语义 → **Replan**
- 明显非出行 → **Reject**

**Run Orchestrator** 在 Plan/Replan 下启动；优先产出通过校验的 Top-K 路线。前置下界已经不可行，或检索后所有候选都违反硬约束时，返回可解释的非路线结果。

### 3.2 Plan Run 六段式 + 热/冷路径

**业务六段（冷路径全量执行）：**

| 段 | 节点 | 职责 |
|----|------|------|
| 1 | `constraint_extract` + `constraint_compile` + `planning_decision` | 提取显式事实，编译 Hard/Soft/Policy，并做前置下界判断 |
| 2 | `activity_blueprint` + `blueprint_compile` + `poi_retrieve` | 构思语义槽位，做无 POI 时间预检，再按槽位召回候选 |
| 3 | `route_generate` | 用绝对时间与交通段联合搜索 **M 条**候选路线 |
| 4 | `route_validate` | 硬约束：时长、预算、营业、可达性 |
| 5 | `route_evaluate` | 合法路线多维打分（执行度、质量、偏好） |
| 6 | `route_present` | 返回 **Top-K**（K=1～3）+ assumptions |

**热路径（跳过 2～5 的全量重算）：**

```
constraint_extract
    → route_bundle_search     ← 向量检索线下 RouteBundle
        ├─ HOT（score ≥ 阈值）
        │     → light_validate → light_adapt → bundle_rerank → route_present
        └─ COLD
              → poi_retrieve → route_generate → route_validate
              → route_evaluate → route_present
              → (async) 写入 RouteBundle 索引
```

**耗时与线下化：** 最耗时为 [3] 多路线生成、[4] 校验（地图 API）、[5] 全量评估。RouteBundle 线下预存已 optimize、已校验、已评分的路线；线上 HOT 仅做轻量复验与 rerank。详见 [`graph-state-design.md`](graph-state-design.md)。

**`failure_directed_repair`：** 冷路径 `valid_routes` 为空时最多修复 2 轮；按 `missing_candidate / temporal_conflict / opening_hours / budget / spatial` 原因执行局部扩大半径、移动或删除 optional/policy 槽位。命名地点、显式时间、排除项和硬预算不可被改写，也不会切换到另一座城市。仍不可行时返回 `infeasible`，不提升非法路线。

**Top-K 输出：** 评估完成后取 `final_score` 最高的 1～3 条；分数接近时可返 2 条供用户点选，**不是澄清问答**。

### 3.3 Replan 模式节点图

```
replan_parse（删除/替换/追加/改偏好）
    → lock_confirmed_stops
    → partial_retrieval
    → local_optimize（最多 8 个提案）
    → validate_delta（统一 RouteJudge）
    → render_diff（通过则原子提交；失败则保留原路线）
```

### 3.4 编排中的中断与恢复

| 事件 | 行为 |
|------|------|
| 用户中途发新消息 | 取消当前 Run，Turn Orchestrator 重新路由 |
| 工具超时 | 标注 `degraded=true`；只有规则兜底路线通过 RouteJudge 才能输出 |
| LLM 结构化解析失败 | 重试 1 次 → 规则 intent + 默认场景模板 → 继续 Plan |
| 校验失败 | 仅放宽系统假设并重试一次；仍失败则返回 `infeasible` 或 `change_rejected` |
| 检索结果为空 | 扩大系统推断的范围后重试；仍为空则返回 `no_candidate`/不可行说明 |

---

## 4. 工具的介入与调用设计

### 4.1 工具分类

| 类型 | 示例 | 调用时机 | 谁决定调用 |
|------|------|---------|-----------|
| **检索类** | POI、RouteBundle、UGC | constraint_extract 后 / 冷路径 poi_retrieve | 编排器固定 |
| **推断类** | 逆地理、场景分类 | constraint_extract | 编排器固定 |
| **计算类** | 距离、路线组合、排程 | route_generate / validate | 编排器固定 |
| **事实类** | 营业、当前时间 vs return_by | light_validate / route_validate | 条件触发 |
| **LLM 自选类** | POI 详情、文案 | route_present 可选 | Tool Router |

### 4.2 推荐向检索（模糊输入的关键）

用户输入越模糊，检索越依赖 **推荐信号**，而非精确过滤：

| 用户输入 | 检索策略 |
|---------|---------|
| 「附近有什么好玩的」 | 位置半径 + 高评分 + 热门模板 + 画像品类 |
| 「徐汇逛吃」 | 区域 + MIXED 场景 + 默认 3 站逛吃模板 |
| 「带小孩出去」 | 场景=亲子 + 默认时长放宽 + 亲子友好 POI tag |

`poi_rank` 在模糊输入时 **提高** `quality_score`、热门度、画像匹配权重，降低对缺失 budget 的惩罚。

### 4.3 LLM 与工具的职责切分

| 职责 | 负责方 |
|------|--------|
| 约束提取与补全 | constraint_extract（规则 + Profile + 可选 LLM） |
| POI 候选 | poi_retrieve（冷路径） |
| 多条候选路线 | route_generate（组合/Optimizer；HOT 跳过） |
| 合法性 | route_validate / light_validate |
| 排序与 Top-K | route_evaluate / bundle_rerank |
| 推荐理由文案 | route_present（模板 + 可选 LLM） |

### 4.4 Tool Router

1. Plan/Replan Run 内允许检索与推断类工具
2. 去重与缓存
3. 单 Run LLM 自选工具上限（如 3 次）

---

## 5. 提示词形态与缓存复用设计

### 5.1 提示词分层结构

```
L0: System Contract     — 单 Agent；显式约束优先；不可把非法路线描述为成功
L1: Mode Template       — Plan / Replan / Adapt / PlanningReply
L2: Task Payload        — 意图、assumptions、候选 POI、画像摘要
L3: Dialog Window        — 最近 K 轮 + 当前 utterance
```

### 5.2 各模式 Prompt 形态

| 模式 | L1 要点 | 输出 schema |
|------|---------|-------------|
| **constraint_extract** | 提取+补全；列 assumptions；含 return_by | `Constraints` |
| **route_generate** | 从 candidate_pois 组合 M 条路线 | `list[RoutePlan]` |
| **route_evaluate** | 按 execution/quality/preference 打分 | `list[ScoredRoute]` |
| **route_present** | Top-K + 「为您推荐…」 | `RoutePresentResult` |
| **replan_parse** | 识别修订类型 | `ReplanIntent` |
| **render_route** | 开场必须是「为您推荐…」+ assumptions 摘要 | `RoutePresentation` |

### 5.3 结构化输出约束

- 主输出为 **`route_results`（Top-K 列表）**，每条含 `route` + `scores` + `assumptions`。
- 非路线结果使用 `PlanningDecision` + `Presentation`，不生成自由文本追问协议。

### 5.4 缓存复用

| 缓存类型 | 复用场景 | 失效条件 |
|---------|---------|---------|
| RouteBundle 向量索引 | 相似约束 query | HOT 路径 |
| Constraint Cache | 相似 query 约束提取 | 用户否定、Replan |
| POI 检索 Cache | 同 district+tags | 位置变化 |
| Tool Result | 逆地理、POI 详情 | ttl |

Plan 模式可积极复用 Retrieval Cache；前置判断和最终 RouteJudge 必须按本轮显式约束重新执行。

---

## 6. 结构化会话记忆、上下文瘦身与输出管理

### 6.1 记忆分层

| 记忆 | 内容 | 进入 Prompt |
|------|------|------------|
| **Working Memory** | RouteIntent、assumptions、current_route | L2 |
| **User Profile Snapshot** | 长期偏好 | L2（推荐核心） |
| **Dialog Memory** | 最近轮次 | L3 摘要 |
| **Confirmed / Rejected** | 用户确认或拒绝的 POI | L2 高优先级 |

### 6.2 SessionState（持久化规划结果）

```
SessionState:
  session_id
  turn_count
  mode: "planning" | "replanning" | "reviewing" | "completed"

  route_intent: RouteIntent
  assumptions: list[Assumption]       # 系统推断，用户可见可推翻
  current_route: RoutePlan | null
  confirmed_stop_ids: list[str]
  rejected_poi_ids: list[str]

  dialog_summary: str
  recent_turns: list[Turn]

  run_artifacts:
    last_candidate_pois: list[ref]
    last_template_id: str | null
```

**不再有 `pending_slots`**——缺失已在 `constraint_extract` 转为 `assumptions`。

### 6.3 输出管理

**Layer 1 结构化输出类型：**

| 类型 | 场景 |
|------|------|
| `route` | Top-1 推荐（含 assumptions） |
| `multi_route` | Top-2/3 并列推荐（评估分数接近） |
| `diff` | Replan 变更 |
| `degraded_route` | 降级兜底 |
| `reject` | 非出行意图 |

**模糊输入的首条回复必含：**

```json
{
  "reply_type": "route",
  "presentation": {
    "title": "为您推荐的徐汇逛吃路线",
    "summary": "约 3 小时 · 3 站 · 人均约 150 元",
    "highlights": ["...", "..."]
  },
  "meta": {
    "assumptions": [
      "未指定预算，按您历史偏好默认人均 150 元",
      "未指定时长，默认半日逛吃约 3 小时",
      "未指定区域，已根据当前位置推荐徐汇区"
    ]
  }
}
```

用户若不满意，**用修订语句反馈**（「预算 100」「换静安」），走 Replan/新 Plan，**不是回答澄清问题**。

---

## 7. 会话状态与运行共建

### 7.1 共建方式

```
用户模糊输入 ──► constraint_extract ──► route_bundle_search?
  HOT ──► Top-K 路线 + assumptions
  COLD ──► 六段流水线 ──► Top-K
用户「第二家换日料」──► Replan
用户「预算改成 100」──► constraint_extract + Replan（推翻 assumption）
用户「就这个」──► confirmed_stop_ids
```

### 7.2 状态机（无 CLARIFYING）

```
INIT → PLANNING（首条输入直接规划）
         │
         ▼
     REVIEWING（展示推荐路线 + assumptions）
         │
    ┌────┼────┐
    ▼    ▼    ▼
COMPLETED  REPLANNING  PLANNING（重新规划）
```

### 7.3 假设的可推翻性

- `assumptions` 在 UI 以 **可编辑标签 / 一句话修订** 展示。
- 用户说「不要默认 150，要 100」→ 更新 intent → Replan，**不从澄清流程绕路**。

---

## 8. 回复机制设计

### 8.1 回复类型

| 类型 | 触发 | 用户感知 |
|------|------|---------|
| **RouteReply** | Plan 成功 Top-1 | 「为您推荐…」+ 路线 + assumptions + scores |
| **MultiRouteReply** | Top-K≥2 | 多条方案卡片，点选即可 |
| **DiffReply** | Replan 成功 | 改了哪些站 |
| **DegradedReply** | 工具/LLM 降级 | 仍有路线 + 原因 |
| **ClarificationReply** | 缺少不可安全推断的地点或时间 | 结构化补充项，不提交路线 |
| **InfeasibleReply** | 当前硬约束下无合法路线 | 原因 + 可执行调整建议 |
| **RejectReply** | 非出行意图 | 简短引导 |

`AssumedRouteReply` 已合并进 RouteReply；澄清和不可行是明确业务结果，不是运行失败。

### 8.2 AgentReply envelope

```
AgentReply:
  reply_type: "route" | "multi_route" | "diff" | "degraded_route" | "clarification" | "infeasible" | "reject"
  planning_outcome: "route_ready" | "clarification_required" | "infeasible" | "change_applied" | "change_rejected" | ...
  structured: list[RoutePlanResult]   # Top-K
  presentation:
    title: str                    # 「为您推荐…」
    summary: str
    highlights: list[str]
    actions: ["采纳方案 1", "看备选", "换一批", "调整预算…"]
  meta:
    plan_path: "hot" | "cold"
    assumptions: list[str]
    relaxed_constraints: list
    degraded: bool
    planning_decision: dict | null
    pending_change: dict | null
    next_suggested_user_moves: list[str]   # 修订示例，非澄清问题
```

### 8.3 流式节奏

```
phase: extracting      → 「正在理解您的需求…」
phase: bundle_search  → 「正在匹配推荐路线…」（HOT）
phase: retrieving     → 「正在挑选地点…」（COLD）
phase: generating     → 「正在生成候选路线…」
phase: evaluating     → 「正在评估最优方案…」
phase: complete       → Top-K 整包
```

### 8.4 错误与恢复

| 失败 | 用户可见 |
|------|---------|
| intent 解析失败 | 按「附近推荐」默认场景出路线 + assumptions |
| 检索为空 | 只放宽系统假设后重试；仍为空则返回不可行说明 |
| 校验不可行 | auto_relax 后返回 `infeasible`，不输出非法候选 |
| LLM 超时 | 规则路线通过 RouteJudge 后输出；否则返回不可行说明 |

---

## 9. 跨维度示例

**场景：模糊输入 → 直接推荐 → 修订**

| Turn | 用户 | 模式 | 回复要点 |
|------|------|------|---------|
| 1 | 「附近有什么好玩的」 | Plan | RouteReply：3 站；assumptions 含默认时长、预算、基于定位的区域 |
| 2 | 「第二家换成咖啡」 | Replan | DiffReply：1 站替换 |
| 3 | 「预算总共 200 以内」 | Replan | DiffReply：换低价 POI；更新 assumptions |

该示例中不需要 Clarify；只有关键前提不可安全推断时才进入结构化补充。

---

## 10. 单 Agent 架构说明

```
┌──────────────────────────────────────────┐
│         Route Planner Agent               │
│         （单个 LangGraph StateGraph）      │
│                                          │
│  Turn 路由: Plan | Replan | Reject       │
│                                          │
│  Plan: constraint_extract → bundle_search? → … → route_present │
│  详见 graph-state-design.md                                  │
│                                          │
│  共享: GraphState / SessionState         │
└──────────────────────────────────────────┘
```

- **不是** Multi-Agent：校验、检索、优化均为 **节点或工具**，不是独立对话 Agent。
- 后续若加并行 Validator，仍是 **单 Graph 内并行节点**，主 Agent 汇总决策（见工程阶段扩展，非 v1 必需）。

---

## 11. 设计检查清单

- [ ] Plan 是否六段式且输出 Top-K？
- [ ] HOT 路径是否跳过全量 generate/evaluate？
- [ ] 冷路径是否异步回填 RouteBundle？
- [ ] `constraint_extract` 是否含 return_by / assumptions？
- [ ] `assumptions` 是否在 UI 可见且可被用户一句话推翻？
- [ ] 校验失败是否只放宽 assumptions，并禁止提升非法路线？
- [ ] `planning_outcome` 是否与 `run_status` 分离？
- [ ] Replan 失败是否保留原路线并写入 `pending_change`？
- [ ] Replan 是否锁定 confirmed stops？
- [ ] 是否保持 **单 Agent + 两层编排**？
- [ ] 流式是否只 narrate 进度，JSON 整包交付？

---

## 12. 与工程文档的边界

| 本文档（Agent 运行时） | 工程 README |
|----------------------|-------------|
| 单 Agent、推荐优先、可行性优先 | API、MQ、DB 部署 |
| Plan 六段 + 热/冷路径 | [`graph-state-design.md`](graph-state-design.md) |
| RouteBundle 线下索引 | 工程 README（数据层） |

两者通过 **`RoutePlan.assumptions` / `AgentReply.meta.assumptions`** 对齐。
