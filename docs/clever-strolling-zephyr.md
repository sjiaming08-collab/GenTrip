# P2 实现计划：Turn Orchestrator + auto_relax + SessionState + AgentReply

> 基于 `docs/agent-runtime-design.md` 第 2~8 节 和 `docs/graph-state-design.md` 第 7 节，在现有 Step A 冷路径之上增强。

---

## Context

当前 GenTrip 是一个 **纯线性冷路径**：每轮从零开始，无 Plan/Replan/Reject 路由，校验失败只降级不重试，响应格式扁平无 reply_type 分化。P2 目标是在不引入向量数据库的前提下，补齐 **编排层** 和 **鲁棒性**，为后续 P3（Replan）和 Step B（热路径）打基础。

---

## 变更总览

| # | 模块 | 操作 | 文件 |
|---|------|------|------|
| 1 | SessionState + RouteIntent 模型 | **新建** | `backend/src/models/session.py` |
| 2 | AgentReply 信封模型 | **新建** | `backend/src/models/reply.py` |
| 3 | turn_orchestrate 节点 | **新建** | `backend/src/graph/nodes/turn_orchestrate.py` |
| 4 | reject_reply 节点 | **新建** | `backend/src/graph/nodes/reject_reply.py` |
| 5 | auto_relax 节点 | **新建** | `backend/src/graph/nodes/auto_relax.py` |
| 6 | GraphState 扩展 | **修改** | `backend/src/graph/state.py` |
| 7 | 条件分支图拓扑 | **重写** | `backend/src/graph/plan_graph.py` |
| 8 | PlanService 会话管理 | **修改** | `backend/src/services/plan_service.py` |
| 9 | API schemas + routes | **修改** | `backend/src/api/schemas.py`, `routes.py` |
| 10 | 模型 re-export | **修改** | `backend/src/models/__init__.py` |
| 11 | 前端类型同步 | **修改** | `frontend/src/types/index.ts` |
| 12 | 测试 | **新建** | `backend/tests/test_turn_orchestrate.py` 等 |

---

## 一、新建模型

### 1.1 `backend/src/models/session.py` — SessionState + RouteIntent

```python
# 设计文档 6.2 节定义的 SessionState
class RouteIntent(BaseModel):
    """用户出行意图的结构化表示"""
    intent_type: str                          # "travel" | "non_travel"
    primary_intent: str                       # "逛吃" | "看展" | "亲子" | "附近推荐" ...
    secondary_intents: list[str] = []         # 次要意图
    query_understanding: str = ""             # LLM 或规则对 query 的理解摘要

class Turn(BaseModel):
    """单轮对话记录"""
    turn_id: str
    user_query: str
    reply_type: str
    route_results: list[dict] = []
    assumptions: list[dict] = []
    ts: str

class SessionState(BaseModel):
    """跨轮会话状态，通过 session_id 索引"""
    session_id: str
    turn_count: int = 0
    mode: str = "planning"                    # "planning" | "replanning" | "reviewing" | "completed"
    route_intent: RouteIntent | None = None
    assumptions: list[dict] = []              # 累积假设
    current_route: dict | None = None         # 最近一条 RoutePlan
    confirmed_stop_ids: list[str] = []        # 用户确认的站点
    rejected_poi_ids: list[str] = []          # 用户拒绝的 POI
    dialog_summary: str = ""                  # 对话摘要（供 L3 Dialog Window）
    recent_turns: list[Turn] = []             # 最近 K 轮（保留最近 5 轮）

    def add_turn(self, turn: Turn) -> None:
        self.recent_turns.append(turn)
        if len(self.recent_turns) > 5:
            self.recent_turns = self.recent_turns[-5:]
        self.turn_count += 1
```

**复用现有模型：** `Assumption` (来自 `models/constraints.py`)，`RoutePlanResult` (来自 `models/route.py`)

### 1.2 `backend/src/models/reply.py` — AgentReply 信封

```python
# 设计文档 8.2 节定义的 AgentReply envelope

class ReplyType(str, Enum):
    ROUTE = "route"
    MULTI_ROUTE = "multi_route"
    DIFF = "diff"
    DEGRADED_ROUTE = "degraded_route"
    REJECT = "reject"

class AgentReplyMeta(BaseModel):
    plan_path: str | None = None             # "hot" | "cold"
    assumptions: list[dict] = []
    relaxed_constraints: list[str] = []
    degraded: bool = False
    next_suggested_user_moves: list[str] = []  # "换日料", "预算100", "换静安" ...

class AgentReply(BaseModel):
    reply_type: ReplyType
    structured: list[dict] = []               # RoutePlanResult dicts
    presentation: dict | None = None          # Presentation dict
    meta: AgentReplyMeta
```

---

## 二、新建节点

### 2.1 `turn_orchestrate` — Turn Orchestrator（设计文档 3.1 节）

**读取：** `user_query`, `session_id`

**逻辑（纯规则，不调 LLM）：**

```
1. 非出行意图检测 → turn_mode = "reject"
   关键词匹配: 股票/基金/天气/新闻/翻译/写代码/...
   → 设置 route_intent.intent_type = "non_travel"

2. 有 current_route 且含修订语义 → turn_mode = "replan"
   修订关键词: 换/替换/改成/不要/删/去掉/加/增加/追加/改预算/改时间/...
   → 设置 route_intent.intent_type = "revision"

3. 无 current_route 或 "重新规划" → turn_mode = "plan" (default)
   重新规划关键词: 重新规划/重新来/换个方案/再来一条/...
   → 设置 route_intent.intent_type = "new_plan"

4. 其余 → turn_mode = "plan" (default)
```

**写入：** `turn_mode`, `route_intent` (dict), `run_mode`, 更新 `current_phase`

**复用：** `phase_update()` from `state.py`

### 2.2 `reject_reply` — RejectReply（设计文档 8.1 节）

**逻辑：** 纯模板，不调 LLM
- 设置 `run_status = "completed"`
- 生成简短引导文案 → `presentation`
- `reply_type = "reject"`
- `next_suggested_user_moves` 给出出行场景引导（如 "附近有什么好玩的"、"徐汇逛吃"）

**输出示例：**
```json
{
  "reply_type": "reject",
  "presentation": {
    "title": "抱歉，我还不太擅长这类问题",
    "summary": "我可以帮你规划出行路线，试试这些：",
    "highlights": ["附近有什么好玩的", "徐汇逛吃", "黄浦区看展览再喝咖啡"]
  },
  "meta": { "next_suggested_user_moves": ["附近有什么好玩的", "徐汇逛吃"] }
}
```

### 2.3 `auto_relax` — 约束自动放宽（设计文档 3.4 节）

**触发条件：** `route_validate` 后 `valid_routes` 为空

**逻辑：**
```
1. 读取 relax_attempt 计数器（默认 0）
2. 若 relax_attempt >= 1（已重试过）→ 不再重试，用 least-violating route，标记 degraded
3. 若 relax_attempt == 0 → 执行放宽:
   a. budget: budget_per_person *= 1.3（上浮 30%）
   b. time: 若 time_budget_minutes 存在 → +60min；若 return_by 存在 → 推迟 1h
   c. geo: district 拓宽为 citywide（上海）
   d. 记录每项放宽到 relaxed_constraints[]
   e. relax_attempt += 1
4. 返回重试 → 跳回 poi_retrieve（重新检索更广范围的 POI）
```

**GraphState 新增字段：** `relax_attempt: int`（默认 0）

**读取：** `constraints`, `relax_attempt`, `relaxed_constraints`
**写入：** 更新后的 `constraints`（dict）, `relax_attempt`, `relaxed_constraints`

---

## 三、GraphState 扩展

在 `backend/src/graph/state.py` 中新增字段：

```python
# L0 RUN_META 新增
turn_mode: str                    # "plan" | "replan" | "reject" — Turn Orchestrator 写入
relax_attempt: int                # auto_relax 重试计数，默认 0

# L2 REASONING 新增
route_intent: Optional[dict]      # RouteIntent 序列化，turn_orchestrate 写入

# L3 WORKING 新增
# (现有字段不变)
```

`build_initial_state()` 新增默认值：
```python
turn_mode="plan",
relax_attempt=0,
route_intent=None,
```

---

## 四、图拓扑变更

### 4.1 `plan_graph.py` 重写

```python
def build_plan_graph():
    graph = StateGraph(GraphState)

    # --- 注册所有节点 ---
    graph.add_node("turn_orchestrate", turn_orchestrate)
    graph.add_node("constraint_extract", constraint_extract)
    graph.add_node("geo_resolve", geo_resolve)
    graph.add_node("poi_retrieve", poi_retrieve)
    graph.add_node("route_generate", route_generate)
    graph.add_node("route_validate", route_validate)
    graph.add_node("auto_relax", auto_relax)
    graph.add_node("route_evaluate", route_evaluate)
    graph.add_node("route_present", route_present)
    graph.add_node("reject_reply", reject_reply)

    # --- 入口：Turn Orchestrator ---
    graph.set_entry_point("turn_orchestrate")

    # --- Turn Orchestrator 三路分发 ---
    graph.add_conditional_edges(
        "turn_orchestrate",
        lambda s: s["turn_mode"],
        {
            "plan": "constraint_extract",
            "replan": "constraint_extract",   # P3 前 fallback 到 plan
            "reject": "reject_reply",
        }
    )

    # --- 冷路径主链 ---
    graph.add_edge("constraint_extract", "geo_resolve")
    graph.add_edge("geo_resolve", "poi_retrieve")
    graph.add_edge("poi_retrieve", "route_generate")
    graph.add_edge("route_generate", "route_validate")

    # --- auto_relax 条件分支 ---
    graph.add_conditional_edges(
        "route_validate",
        lambda s: "auto_relax" if (not s.get("valid_routes") and s.get("relax_attempt", 0) < 1) else "route_evaluate",
        {
            "auto_relax": "auto_relax",
            "route_evaluate": "route_evaluate",
        }
    )
    # auto_relax 重试 → 回到 poi_retrieve
    graph.add_edge("auto_relax", "poi_retrieve")

    # --- 收尾 ---
    graph.add_edge("route_evaluate", "route_present")
    graph.add_edge("route_present", END)
    graph.add_edge("reject_reply", END)

    return graph
```

**关键设计：**
- Replan 当前 fallback 到 `constraint_extract`（完整 plan 路径）；在 state 中通过 `run_mode="replan"` 标记，后续 P3 替换为真正的 replan 子图
- auto_relax 只重试 1 次（`relax_attempt < 1`），重试后回到 `poi_retrieve` 而非 `route_generate`（因为放宽了 geo/budget，需要重新检索更广范围的 POI）
- 第二次校验仍失败 → 直接走 `route_evaluate`（用 degraded best-effort 路线）

---

## 五、PlanService 变更

```python
class PlanService:
    def __init__(self):
        self._agent = create_plan_agent()
        self._sessions: dict[str, SessionState] = {}  # 内存会话存储

    def _get_or_create_session(self, session_id: str | None) -> tuple[str, SessionState]:
        if session_id and session_id in self._sessions:
            return session_id, self._sessions[session_id]
        sid = session_id or str(uuid4())
        session = SessionState(session_id=sid)
        self._sessions[sid] = session
        return sid, session

    def _save_session(self, session: SessionState, state: dict) -> None:
        """Run 结束后持久化会话快照"""
        if state.get("route_results"):
            session.current_route = state["route_results"][0].get("route") if isinstance(state["route_results"][0], dict) else state["route_results"][0].route.model_dump()
        if state.get("assumptions"):
            session.assumptions = state["assumptions"]
        if state.get("route_intent"):
            session.route_intent = RouteIntent.model_validate(state["route_intent"])
        turn = Turn(turn_id=state["turn_id"], user_query=state["user_query"], ...)
        session.add_turn(turn)

    async def run_plan(self, query, *, user_id=None, user_lat=None, user_lng=None, session_id=None):
        sid, session = self._get_or_create_session(session_id)
        initial = build_initial_state(query, ..., session_id=sid)
        # 注入会话上下文
        if session.current_route:
            initial["session_current_route"] = session.current_route
        final_state = await self._agent.ainvoke(initial)
        self._save_session(session, final_state)
        return final_state
```

---

## 六、API 层变更

### 6.1 `schemas.py` — 新增 AgentReply

```python
class AgentReplyResponse(BaseModel):
    reply_type: str                              # "route" | "multi_route" | "diff" | ...
    run_id: str
    session_id: str | None
    structured: list[dict] = []
    presentation: dict | None = None
    meta: dict = {}                              # plan_path, assumptions, relaxed_constraints, degraded, next_suggested_user_moves

class SessionResponse(BaseModel):
    session_id: str
    turn_count: int
    current_route: dict | None
    assumptions: list[dict]
```

### 6.2 `routes.py` — 新端点 + 响应升级

```python
@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    """获取会话状态（用于前端恢复）"""
    ...

@router.post("/routes/plan", response_model=AgentReplyResponse)
async def plan_route(request: PlanRequest):
    """返回 AgentReply 信封而非扁平 PlanResponse"""
    state = await _plan_service.run_plan(...)
    turn_mode = state.get("turn_mode", "plan")
    # 根据 turn_mode 组装不同 reply_type
    if turn_mode == "reject":
        return AgentReplyResponse(reply_type="reject", ...)
    if state.get("degraded"):
        reply_type = "degraded_route"
    elif len(state.get("route_results", [])) >= 2:
        reply_type = "multi_route"
    else:
        reply_type = "route"
    ...
```

---

## 七、前端类型同步

`frontend/src/types/index.ts` 新增：

```typescript
export type ReplyType = 'route' | 'multi_route' | 'diff' | 'degraded_route' | 'reject'

export interface AgentReplyMeta {
  plan_path?: string
  assumptions: Assumption[]
  relaxed_constraints: string[]
  degraded: boolean
  next_suggested_user_moves: string[]
}

export interface AgentReplyResponse {
  reply_type: ReplyType
  run_id: string
  session_id?: string
  structured: RoutePlanResult[]
  presentation?: Presentation
  meta: AgentReplyMeta
}
```

前端 `useRoutePlan.ts` 的 `submitQuery` 返回类型从 `RoutePlanResponse` 改为 `AgentReplyResponse`，按 `reply_type` 分流渲染。

---

## 八、测试计划

| 测试文件 | 覆盖 |
|----------|------|
| `tests/test_turn_orchestrate.py` | 非出行检测、修订语义检测、默认 plan 路由 |
| `tests/test_auto_relax.py` | 放宽 budget/time/geo、重试计数、二次失败降级 |
| `tests/test_session_state.py` | SessionState CRUD、跨轮累积 |
| `tests/test_reject_reply.py` | RejectReply 模板输出 |
| `tests/test_plan_graph_branches.py` | 条件分支：plan→cold / reject→reject_reply / validate→auto_relax |
| `tests/test_agent_reply.py` | AgentReply 序列化，各 reply_type 完整性 |

---

## 九、实现顺序

```
Phase A — 数据层（~30min）
  [1] models/session.py     → SessionState + RouteIntent + Turn
  [2] models/reply.py       → AgentReply + ReplyType + AgentReplyMeta
  [3] models/__init__.py    → re-export

Phase B — 节点层（~45min）
  [4] graph/state.py        → 新增 turn_mode, relax_attempt, route_intent
  [5] nodes/turn_orchestrate.py → 三路分发逻辑
  [6] nodes/reject_reply.py → RejectReply 模板
  [7] nodes/auto_relax.py   → 约束放宽 + 重试控制

Phase C — 编排层（~30min）
  [8] plan_graph.py         → 重写：条件分支拓扑
  [9] plan_service.py       → 会话存储 + 上下文注入

Phase D — API + 前端（~30min）
  [10] api/schemas.py       → AgentReplyResponse
  [11] api/routes.py        → 响应升级 + session 端点
  [12] frontend types       → 类型同步

Phase E — 测试验证（~45min）
  [13] 6 个新测试文件
  [14] 回归：现有 13 个测试全部通过
  [15] E2E: evaluate_route_plans.py 仍能正常跑完
```

---

## 十、验证方式

```bash
# 1. 后端测试
cd backend && python -m pytest tests/ -v

# 2. 回归：冷路径 E2E 评估
python scripts/evaluate_route_plans.py

# 3. 手动 curl 验证新功能
# 非出行 → reject
curl -X POST http://localhost:8080/api/v1/routes/plan \
  -H "Content-Type: application/json" \
  -d '{"query": "今天股票怎么样", "session_id": "test-001"}'

# 出行 → plan (AgentReply envelope)
curl -X POST http://localhost:8080/api/v1/routes/plan \
  -H "Content-Type: application/json" \
  -d '{"query": "徐汇逛吃", "session_id": "test-001"}'

# 会话恢复
curl http://localhost:8080/api/v1/sessions/test-001

# 4. 前端 (手动)
cd frontend && npm run dev
# 输入非出行 query → 验证 UI 显示 reject 引导
# 输入出行 query → 验证 UI 显示路线 + assumptions
```

---

## 十一、已知限制 & 后续衔接

| 限制 | P3 解决 |
|------|---------|
| Replan 路由到 plan（非真正的增量重算） | P3 实现 replan 六节点 |
| Session 存储是内存 dict（重启丢失） | P3 加 Redis/DB 持久化 |
| RouteIntent 检测纯规则（无 LLM） | P3 可选 LLM 增强意图分类 |
| auto_relax 只放宽 budget/time/geo | P3 可加 POI 品类放宽 |
| AgentReply 中 `diff` 类型未使用 | P3 Replan 后启用 |
