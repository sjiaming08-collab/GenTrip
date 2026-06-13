# GraphState 设计 — Plan Run 与热/冷路径

> 本文档定义单 Agent Plan 流程下的 **GraphState**、**六段式流水线**、**热路径（RouteBundle 向量检索）** 与 **冷路径（全量生成评估）**。  
> 对齐原则：**零澄清、输入即推荐、单 Agent、Top-K 输出**。

---

## 1. Plan Run 六段式流水线

一次 Plan Run 的业务语义（与 Agentic Loop 对应）：

```
┌────────────────────────────────────────────────────────────────────────┐
│                         PLAN RUN（六段）                                │
└────────────────────────────────────────────────────────────────────────┘

[1] constraint_extract     提取 + 补全约束（位置、想玩什么、几点回家…）→ assumptions
[2] poi_retrieve           按约束召回候选 POI
[3] route_generate         在 POI 上生成多条候选路线（M 条）
[4] route_validate         硬约束校验（合法性 / 可执行性）
[5] route_evaluate         对合法路线多维评估排序
[6] route_present          返回 Top-K 条最可靠路线 + assumptions
```

| Agentic Loop | 六段 |
|--------------|------|
| OBSERVE | 入口（L1 INPUT） |
| REASON | [1] constraint_extract |
| ACT | [2] poi_retrieve → [3] route_generate |
| REFLECT | [4] route_validate → [5] route_evaluate |
| RESPOND | [6] route_present |

**Run 不变量：**

- 每条用户输入必须产出 **至少 1 条** 推荐路线（Top-K 默认 K=1～3）。
- **永不** `waiting_user` / Clarify。
- Run 成功：`run_status == "completed"` 且 `route_results` 非空。

---

## 2. 热路径 vs 冷路径

最耗时的是 **[3] 生成多条路线 + [4] 全量校验 + [5] 全量评估**（尤其含地图 API、LLM、组合爆炸）。  
因此 Plan Run **优先走向量检索预计算路线包（RouteBundle）**，miss 时才走冷路径。

```
constraint_extract
        │
        ▼
route_bundle_search          ← 向量检索线下 RouteBundle 索引（Top-5）
        │
        ├── bundle_hit（score ≥ 阈值）──► 热路径 HOT
        │       light_validate
        │       light_adapt（替换失效 POI / 微调时间）
        │       bundle_rerank（轻量重排，非全量 evaluate）
        │       route_present → END
        │
        └── bundle_miss ──► 冷路径 COLD
                poi_retrieve
                route_generate（M 条）
                route_validate
                route_evaluate
                route_present → END
                └── 异步：结果写入 RouteBundle 索引（越用越热）
```

| 路径 | 触发 | 跳过 | 典型延迟 |
|------|------|------|---------|
| **HOT** | `bundle_match_score ≥ 0.75`（可调） | 全量 POI 组合、M 条生成、全量 evaluate | 100ms～800ms |
| **COLD** | 检索 miss / 约束过偏 / 用户否定命中 bundle | 无 | 2s～15s |

`plan_path: "hot" | "cold"` 写入 GraphState，供日志与 SLO 统计。

---

## 3. 步骤耗时与线下化策略

| 步骤 | 典型耗时 | 瓶颈 | 线下化 |
|------|---------|------|--------|
| [1] constraint_extract | 50ms～2s | LLM（若用） | 规则 + 场景表；常见 query 模板 |
| bundle_search | 50～200ms | 向量检索 | **RouteBundle 索引线下建好** |
| [2] poi_retrieve | 100ms～1s | ES / 向量 | POI 向量库、索引线下维护 |
| [3] route_generate | **0.5s～8s** | LLM / 组合 | **Bundle 内已含生成结果** |
| [4] route_validate | 200ms～2s | **地图 API** | 骨架线下验过；线上 light_validate |
| [5] route_evaluate | 50ms～1s×M | 多条路线评分 | **分数预写入 Bundle**；线上只 rerank Top-5 |
| [6] route_present | 50ms～1s | LLM 文案（可选） | UGC 摘要 / 标题模板线下备 |

**线上必须保留（即使 HOT）：** 当前位置、当前时刻、`return_by`（几点回家）、营业状态、用户本轮否定。

---

## 4. RouteBundle（线下数据集）

每条 RouteBundle 是 **冷路径一次完整产物的冻结快照**：

```python
RouteBundle:
  id: str
  # ---- 检索 ----
  search_text: str                    # 用于 embedding 的约束摘要
  constraint_embedding: list[float]   # pgvector / Milvus
  tags: list[str]                     # district, purpose, budget_band, ...
  geohash_prefix: str | null          # 位置相关 bundle

  # ---- 预计算路线（已走完 3～5 步）----
  routes: list[RoutePlan]             # 1～3 条已 optimize 的路线
  validation_passed: bool             # 线下校验结论
  scores: {                           # 线下 evaluate
    execution: float                  # 执行度 / 时间裕量
    quality: float
    preference_match: float
  }

  # ---- 元数据 ----
  assumptions_template: list[Assumption]
  poi_ids: list[str]
  generated_at: datetime
  expires_at: datetime | null
  use_count: int
  avg_user_rating: float
```

**线下采集来源：**

1. 规则枚举（区域 × 场景 × 预算档 × 时长档）批量跑冷路径  
2. 高评分用户路线回流  
3. 冷路径异步回填（越用越热）

**线上 HOT：** `embedding(constraint_summary) → Top-5 bundle → light_validate → rerank → Top-K 返回`。

---

## 5. GraphState 总览

```
┌─────────────────────────────────────────────────────────┐
│ L0  RUN_META       run_status, plan_path, degraded      │
├─────────────────────────────────────────────────────────┤
│ L1  INPUT          user_query, lat/lng（Run 内只读）       │
├─────────────────────────────────────────────────────────┤
│ L2  REASONING      constraints, assumptions             │
├─────────────────────────────────────────────────────────┤
│ L3  WORKING        POI / 路线 / 校验 / 评分 中间产物      │
├─────────────────────────────────────────────────────────┤
│ L4  OUTPUT         route_results (Top-K), presentation  │
├─────────────────────────────────────────────────────────┤
│ L5  TELEMETRY      phase_log, stream_events             │
└─────────────────────────────────────────────────────────┘
```

GraphState **不是**专门给条件判断用的，而是 **节点间传递数据的黑板**；条件分支只读取其中少数字段（如 `plan_path`、`bundle_match_score`、`valid_routes` 是否为空）。

---

## 6. 字段定义

### 6.1 L0 — RUN_META

| 字段 | 类型 | 说明 |
|------|------|------|
| `run_id` | `str` | UUID |
| `session_id` | `str \| null` | 会话 |
| `turn_id` | `str` | 对话轮 |
| `run_mode` | `"plan" \| "replan"` | 固定 plan 或 Replan 子图 |
| `run_status` | `"running" \| "completed" \| "failed"` | |
| `plan_path` | `"hot" \| "cold" \| null` | 热/冷路径标记 |
| `current_phase` | `str` | 当前节点名 |
| `error` | `str \| null` | |
| `degraded` | `bool` | 降级（规则兜底 / 放宽约束） |

### 6.2 L1 — INPUT（只读）

| 字段 | 类型 | 说明 |
|------|------|------|
| `user_query` | `str` | |
| `user_id` | `str \| null` | |
| `user_lat` / `user_lng` | `float \| null` | |
| `input_ts` | `str` | ISO8601 |

### 6.3 L2 — REASONING

| 字段 | 类型 | 写入节点 | 说明 |
|------|------|----------|------|
| `constraints` | `Constraints` | `constraint_extract` | 补全后的全量约束 |
| `assumptions` | `list[Assumption]` | `constraint_extract` | 推断假设，对用户可见 |
| `constraint_embedding` | `list[float] \| null` | `constraint_extract` | 供 bundle_search |
| `relaxed_constraints` | `list[str]` | `route_validate`, `auto_relax` | 自动放宽项 |

**Constraints（核心字段）：**

```python
Constraints:
  raw_query: str
  purpose: DINING | SIGHTSEEING | SHOPPING | MIXED
  district: str
  time_budget_minutes: int | null      # 与 return_by 二选一或并存
  return_by: str | null                # "19:00" 几点前到家
  budget_per_person: int
  poi_count: int
  preferred_cuisines: list[str] | null
  activity_tags: list[str] | null      # 想玩的项目
  crowd_tolerance: LOW | MEDIUM | HIGH | null
```

`constraint_extract` 结束后 **核心字段不得为 null**（推断值写入 `assumptions`）。

### 6.4 L3 — WORKING

| 字段 | 类型 | 写入节点 | 说明 |
|------|------|----------|------|
| `bundle_candidates` | `list[RouteBundle]` | `route_bundle_search` | 向量 Top-5 |
| `bundle_match_score` | `float` | `route_bundle_search` | 最高分 |
| `matched_bundle_id` | `str \| null` | `route_bundle_search` | HOT 命中 ID |
| `candidate_pois` | `list[ScoredPoi]` | `poi_retrieve` | 冷路径；Top-N POI |
| `candidate_routes` | `list[RoutePlan]` | `route_generate` | **M 条**候选路线 |
| `valid_routes` | `list[RoutePlan]` | `route_validate` | 校验通过后 |
| `scored_routes` | `list[ScoredRoute]` | `route_evaluate` | 带多维分 |
| `validation_reports` | `list[ValidationReport]` | `route_validate` | 与 candidate 对应 |

**ScoredRoute：**

```python
ScoredRoute:
  route: RoutePlan
  execution_score: float      # 执行度 / 时间裕量
  quality_score: float
  preference_score: float
  final_score: float
  rank: int
```

### 6.5 L4 — OUTPUT

| 字段 | 类型 | 写入节点 | 说明 |
|------|------|----------|------|
| `route_results` | `list[RoutePlanResult]` | `route_present` | **Top-K**，K 默认 1～3 |
| `presentation` | `Presentation` | `route_present` | 标题、摘要、方案卡片 |

**RoutePlanResult：**

```python
RoutePlanResult:
  route: RoutePlan
  source: BUNDLE_HIT | BUNDLE_ADAPTED | COLD_GENERATED | DEGRADED
  bundle_id: str | null
  rank: int
  scores: { execution, quality, final }
```

---

## 7. Plan 图拓扑（完整）

```
START
  → constraint_extract
  → route_bundle_search
       ├─ HOT (score ≥ threshold)
       │     → light_validate
       │     → light_adapt
       │     → bundle_rerank
       │     → route_present → END
       │
       └─ COLD
             → poi_retrieve
             → route_generate
             → route_validate
                  ├─ valid_routes 非空 → route_evaluate
                  └─ 为空 → auto_relax → route_generate 或 poi_retrieve（最多 1 轮）
             → route_evaluate
             → route_present → END
             → (async) bundle_index_ingest
```

### 7.1 MVP 最小图（实现顺序）

**Step A — 仅冷路径六段（无 Bundle）：**

```
constraint_extract → poi_retrieve → route_generate
  → route_validate → route_evaluate → route_present → END
```

**Step B — 加 HOT：**

在 `constraint_extract` 后插入 `route_bundle_search` 分支。

---

## 8. 节点读写矩阵

| 节点 | 读 | 写 |
|------|----|----|
| **constraint_extract** | L1, UserProfile | L2.constraints, L2.assumptions, L2.constraint_embedding |
| **route_bundle_search** | L2 | L3.bundle_*, L0.plan_path, branch |
| **light_validate** | L3.bundle_candidates, L2, L1 | 过滤后 routes |
| **light_adapt** | 同上 | 替换失效 POI，L0.degraded? |
| **bundle_rerank** | bundles + L2 | L3.scored_routes |
| **poi_retrieve** | L2, L1.lat/lng | L3.candidate_pois |
| **route_generate** | L3.candidate_pois, L2 | L3.candidate_routes |
| **route_validate** | L3.candidate_routes, L2 | L3.valid_routes, validation_reports |
| **auto_relax** | validation_reports, L2 | L2.relaxed_constraints, 触发重试 |
| **route_evaluate** | L3.valid_routes, L2 | L3.scored_routes |
| **route_present** | L3.scored_routes 或 rerank 结果, L2.assumptions | L4.route_results, L4.presentation, L0.run_status=completed |

---

## 9. 条件分支（读 GraphState 的字段）

| 位置 | 判断依据 | 分支 |
|------|---------|------|
| `route_bundle_search` | `bundle_match_score ≥ 0.75` | HOT / COLD |
| `route_validate` | `len(valid_routes) > 0` | evaluate / auto_relax |
| `route_present` | `len(scored_routes) ≥ 2` 且分数接近 | 返 Top-2；否则 Top-1 |

---

## 10. Reducer 规则

| 字段 | Reducer |
|------|---------|
| `assumptions` | 按 `slot` merge，后写覆盖 |
| `relaxed_constraints` | append |
| `phase_log` / `stream_events` | append |

---

## 11. 初始 State 工厂

```python
def build_initial_state(user_query, user_lat=None, user_lng=None, user_id=None, session_id=None):
    return {
        "run_id": new_uuid(),
        "session_id": session_id,
        "turn_id": new_uuid(),
        "run_mode": "plan",
        "run_status": "running",
        "plan_path": None,
        "current_phase": "init",
        "error": None,
        "degraded": False,
        "user_query": user_query,
        "user_id": user_id,
        "user_lat": user_lat,
        "user_lng": user_lng,
        "input_ts": utc_now_iso(),
        "constraints": None,
        "assumptions": [],
        "constraint_embedding": None,
        "relaxed_constraints": [],
        "bundle_candidates": [],
        "bundle_match_score": 0.0,
        "matched_bundle_id": None,
        "candidate_pois": [],
        "candidate_routes": [],
        "valid_routes": [],
        "scored_routes": [],
        "validation_reports": [],
        "route_results": [],
        "presentation": None,
        "phase_log": [],
        "stream_events": [],
    }
```

---

## 12. Run 结束验收

```python
assert state["run_status"] == "completed"
assert len(state["route_results"]) >= 1
assert state["constraints"] is not None
assert state["plan_path"] in ("hot", "cold")
# 模糊输入
assert len(state["assumptions"]) >= 1
```

---

## 13. TypedDict 骨架

```python
class GraphState(TypedDict, total=False):
    # L0
    run_id: str
    session_id: Optional[str]
    turn_id: str
    run_mode: str
    run_status: str
    plan_path: Optional[str]
    current_phase: str
    error: Optional[str]
    degraded: bool
    # L1
    user_query: str
    user_id: Optional[str]
    user_lat: Optional[float]
    user_lng: Optional[float]
    input_ts: str
    # L2
    constraints: Optional[dict]
    assumptions: Annotated[list, merge_assumptions]
    constraint_embedding: Optional[list[float]]
    relaxed_constraints: Annotated[list[str], operator.add]
    # L3
    bundle_candidates: list
    bundle_match_score: float
    matched_bundle_id: Optional[str]
    candidate_pois: list
    candidate_routes: list
    valid_routes: list
    scored_routes: list
    validation_reports: list
    # L4
    route_results: list
    presentation: Optional[dict]
    # L5
    phase_log: Annotated[list, operator.add]
    stream_events: Annotated[list, operator.add]
```

---

## 14. 设计检查清单

- [ ] 六段语义在 Graph 节点上有明确映射
- [ ] HOT 路径跳过全量 generate / evaluate
- [ ] COLD 路径产出 `candidate_routes` → `valid_routes` → `scored_routes`
- [ ] 输出为 `route_results` Top-K，不是单条 `route_result`
- [ ] `assumptions` 在 present 阶段带给用户
- [ ] 冷路径结果可异步写入 RouteBundle
- [ ] 无 Clarify / waiting 状态
- [ ] L1 字段 Run 内不被修改

---

## 15. 与 agent-runtime-design.md 的关系

| 文档 | 侧重 |
|------|------|
| `agent-runtime-design.md` | Turn/Replan、回复、Prompt、会话 |
| 本文档 | Plan Run 六段、GraphState 字段、热/冷路径、RouteBundle |

实现时以 **本文档 GraphState + 节点拓扑** 为准。
