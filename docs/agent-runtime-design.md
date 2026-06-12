# GenTrip Agent 运行时设计

> 本文档只讨论 **Agent 运行时行为**：主循环、编排、工具、提示词、会话记忆、状态共建与回复机制。  
> 不涉及数据库选型、部署、网关、监控等工程实现。

---

## 1. 设计目标与边界

GenTrip 不是开放式闲聊 Bot，而是 **「目标导向的多轮规划 Agent」**：

- 用户用自然语言表达出行目标，系统在多轮交互中 **收敛约束**，产出 **可执行路线**。
- 路线生成后，用户仍可 **修订**（换店、跳过、加站、改预算），Agent 在已有上下文上 **增量共建**，而非每轮从零开始。
- 所有 LLM 输出必须 **结构化**（意图、路线、澄清问题），便于校验、展示与后续 Replan。

**Agent 运行时三大模式：**

| 模式 | 触发 | 目标 |
|------|------|------|
| **Plan** | 用户首次提出或重新规划 | 从模糊需求收敛到完整路线 |
| **Clarify** | 约束不足或相互冲突 | 用最少轮次补齐/消解歧义 |
| **Replan** | 已有路线上的局部修改 | 保留已确认部分，重算剩余段 |

---

## 2. 运行时主循环

### 2.1 主循环形态

Agent 运行时不是「一次 Prompt → 一次回答 → 结束」，而是 **「感知 → 决策 → 行动 → 更新状态 → 等待用户」** 的循环：

```
┌─────────────────────────────────────────────────────────────┐
│                     RUNTIME MAIN LOOP                        │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
  [1] 接收用户输入（文本 ± 位置 ± 会话 ID）
        │
        ▼
  [2] 加载会话状态（Working Memory + Dialog Memory + User Profile 摘要）
        │
        ▼
  [3] 意图增量解析（merge，非覆盖）
        │
        ▼
  [4] 路由决策：Clarify │ Plan │ Replan │ Chitchat-Reject
        │
        ├── Clarify ──► 生成澄清问题 ──► 更新状态 ──► 回复用户 ──► 等待下轮
        │
        ├── Plan ──► 检索 + 工具 + 生成/适配 ──► 校验 ──► 回复路线 ──► 等待下轮
        │
        └── Replan ──► 锁定已确认段 ──► 局部重算 ──► 回复 diff ──► 等待下轮
        │
        ▼
  [5] 用户反馈 / 新指令 ──► 回到 [1]
```

**循环终止条件（任一条满足即进入「本轮结束」）：**

- 输出完整路线且用户未继续修订（显式确认或超时静默）。
- 澄清轮次达到上限（如 3 轮），系统给出 **带假设的默认方案** 并标注 `relaxed_constraints`。
- 用户主动结束会话（「就这样」「不用改了」）。

### 2.2 单轮内 vs 跨轮

| 概念 | 含义 |
|------|------|
| **Turn（对话轮）** | 用户发一条消息 → Agent 回复一次，算一轮 |
| **Run（规划运行）** | 一次 Plan/Replan 内部的多节点执行，可在单 Turn 内完成 |
| **Session（会话）** | 多 Turn 共享同一 `session_id`，状态持续累积 |

主循环管 **Turn 级** 调度；编排（第 3 节）管 **Run 级** 节点流水线。

### 2.3 运行时优先级

当多个目标冲突时，Agent 按以下优先级决策：

1. **安全与可行性**（营业、距离、时间窗不可行 → 必须 Clarify 或降级）
2. **用户本轮显式指令**（「不要火锅」覆盖历史偏好）
3. **已确认路线段**（Replan 时不可擅自改动）
4. **会话内累积约束**（前几轮说过的预算、区域）
5. **长期用户画像**（仅作默认补全，不覆盖显式否定）

---

## 3. 编排设计

### 3.1 两层编排

```
Turn Orchestrator（对话级）
    │  决定：Clarify / Plan / Replan
    ▼
Run Orchestrator（规划级）
    │  决定：走哪条生成路径、调用哪些工具、是否提前终止
    ▼
Node Pipeline（节点流水线）
```

**Turn Orchestrator** 输入：用户 utterance + 会话快照。  
输出：`turn_mode` + 更新后的 `RouteIntent` 草案。

**Run Orchestrator** 仅在 `Plan` 或 `Replan` 模式下启动，负责节点图的分支与汇合。

### 3.2 Plan 模式节点图

```
intent_merge
    → constraint_check
        ├─ [slots 缺失] → clarify_compose → END（本 Run 不生成路线）
        └─ [slots 足够] → hybrid_retrieval
                              → poi_rank
                              → template_match
                                  ├─ cache_hit
                                  ├─ adapt_template
                                  └─ full_generate
                              → route_optimize
                              → constraint_validate
                                  ├─ [不可行] → conflict_compose → END（多方案或澄清）
                                  └─ [可行] → render_route → END
```

### 3.3 Replan 模式节点图

Replan **不重新跑完整 Plan**，而是：

```
replan_parse（解析修订意图：删除/替换/追加/改时间）
    → lock_confirmed_stops（冻结用户已确认站点）
    → partial_retrieval（仅在剩余约束下补候选 POI）
    → local_optimize（对未锁定段重排）
    → validate_delta（只校验变更部分）
    → render_diff（输出「改了什么」而非整表重刷）
```

### 3.4 Clarify 模式

Clarify **禁止调用重检索与全量生成**，只允许：

- 读取当前 `RouteIntent` 与 `pending_slots`
- 可选：轻量工具（如「用户是否在某某区」用位置工具一次）
- 输出：**单一聚焦问题** 或 **二选一**（避免一次问五个问题）

Clarify 轮次上限后，进入 **Assumed Plan**：用默认值补全缺失 slot，并在输出中显式标注假设。

### 3.5 编排中的中断与恢复

| 事件 | 行为 |
|------|------|
| 用户中途发新消息 | 若当前 Run 未完成，**取消**当前 Run，Turn Orchestrator 重新路由 |
| 工具超时 | 跳过该工具结果，节点标注 `degraded=true`，继续或转 Clarify |
| LLM 结构化解析失败 | 重试 1 次（缩小 schema）→ 仍失败则 Clarify「请换个说法」 |
| 校验失败 | 不直接报错给用户，走 `conflict_compose` 产出 Plan A/B |

---

## 4. 工具的介入与调用设计

### 4.1 工具分类

| 类型 | 示例 | 调用时机 | 谁决定调用 |
|------|------|---------|-----------|
| **检索类** | POI 搜索、UGC 摘要、模板检索 | Plan/Replan 的 retrieval 阶段 | Run Orchestrator 固定调用 |
| **计算类** | 距离/时长估算、路线优化 | optimize 阶段 | Run Orchestrator 固定调用 |
| **事实类** | 营业状态、天气 | validate 或 adapt 阶段 | 条件触发 |
| **Agent 自选类** | POI 详情、同类替代 | full_generate 内 LLM 可请求 | LLM + Tool Router 审批 |

**原则：关键路径工具由编排器调用，LLM 只在「需要补充事实」时有限自选。**

### 4.2 工具调用协议

每次工具调用携带统一上下文包：

```
ToolContext:
  session_id
  turn_id
  route_intent_snapshot（精简版）
  purpose: "retrieval" | "validate" | "replace_poi" | ...
```

工具返回统一 envelope：

```
ToolResult:
  success: bool
  data: structured payload
  confidence: float
  source: "poi_db" | "ugc" | "map_api" | ...
  ttl_hint: seconds（供缓存层使用）
  degraded: bool
```

### 4.3 LLM 与工具的职责切分

| 职责 | 负责方 |
|------|--------|
| POI 候选从哪来 | 检索工具 + rank |
| 站点顺序、时间轴 | route_optimize 工具 |
| 为什么选这家（文案） | LLM + UGC 工具结果 |
| 是否营业、排队 | 事实类工具 |
| 整段路线 JSON | LLM 在 **候选集合约束下** 填空，或 Optimizer 直出 |

**禁止**：LLM 在无工具佐证时编造 POI 名称、地址、评分。

### 4.4 Tool Router（工具路由审批）

当 LLM 请求自选工具时，Tool Router 检查：

1. 当前模式是否允许（Clarify 模式拒绝检索类工具）
2. 是否重复调用（同一 POI 详情已缓存）
3. 预算：单 Run 最多 N 次 LLM-initiated 工具调用（如 3 次）

### 4.5 工具结果进入上下文的方式

- **不**把原始 JSON 全量塞进 Prompt。
- 经 **Tool Result Compressor** 转为表格化摘要或 Top-K 条目，再进入 LLM 上下文（见第 6 节）。

---

## 5. 提示词形态与缓存复用设计

### 5.1 提示词分层结构

所有 LLM 调用采用 **四层 Prompt 模板**，而非单一长字符串：

```
┌─────────────────────────────────────┐
│ L0: System Contract（不变）          │  角色、输出 schema、禁止事项
├─────────────────────────────────────┤
│ L1: Mode Template（按模式切换）      │  Plan / Clarify / Replan / Adapt
├─────────────────────────────────────┤
│ L2: Task Payload（每 Run 不同）      │  压缩后的意图、候选 POI、模板骨架
├─────────────────────────────────────┤
│ L3: Dialog Window（每 Turn 不同）    │  最近 K 轮对话摘要 + 当前 utterance
└─────────────────────────────────────┘
```

### 5.2 各模式 Prompt 形态

| 模式 | L1 要点 | 输出 schema |
|------|---------|-------------|
| **intent_merge** | 「增量合并，不丢已确认约束；冲突以本轮为准」 | `RouteIntentDelta` |
| **clarify_compose** | 「只问一个问题；给选项不超过 3 个」 | `ClarifyQuestion` |
| **adapt_template** | 「保持骨架；仅替换失效 POI；不改顺序」 | `RoutePlan` |
| **full_generate** | 「只能从候选列表选 POI；不可新增列表外店」 | `RoutePlan` |
| **conflict_compose** | 「说明冲突原因；给 Plan A / Plan B」 | `MultiPlanResponse` |
| **replan_parse** | 「识别操作类型：remove/replace/add/reschedule」 | `ReplanIntent` |
| **render_diff** | 「只描述变更站点；用对比句式」 | `RouteDiff` |

### 5.3 结构化输出约束

- 一律 **JSON Schema / Pydantic** 约束，不用「请用 markdown 列出行程」作为主输出。
- 面向用户的自然语言在 **render** 节点由结构化结果 **二次生成**，便于 UI 与地图层消费同一份 `RoutePlan`。

### 5.4 缓存复用设计（Prompt / 推理层）

这里的「缓存」指 **Agent 运行时复用**，不是工程上的 Redis：

| 缓存类型 | Key | 复用场景 | 失效条件 |
|---------|-----|---------|---------|
| **Intent Cache** | hash(normalized_query + user_profile_version) | 极相似 query 跳过 intent_merge LLM | 会话内出现否定词、Replan |
| **Retrieval Cache** | hash(RouteIntent.core_slots + district) | 同约束下 POI/模板检索结果 | 会话超过 T 分钟、用户改区域 |
| **Template Match Cache** | embedding(query) + slots | template_match 分数 | 模板库版本更新 |
| **Tool Result Cache** | tool_name + args_hash | POI 详情、距离估算 | ttl_hint 或 POI 数据版本 |
| **Prompt Prefix Cache** | L0+L1 固定前缀 | 适配/生成类 LLM 前缀复用（Provider 侧 KV cache） | 模式切换 |

**复用原则：**

- Clarify 模式 **不缓存** LLM 输出（每轮问题应不同）。
- Plan 模式可 aggressively 复用 Retrieval Cache。
- Replan 只复用 **未锁定段** 之外的检索结果。

### 5.5 Few-shot 与动态示例

- Few-shot 不写入 L0，而作为 **Retrieved Examples**：从高质量历史会话检索 1～2 条「相似场景的正确 intent/route」注入 L2。
- 示例也必须 **结构化截断**，只保留 intent + 最终 stops 名称列表，不带长对话。

---

## 6. 结构化会话记忆、上下文瘦身与输出管理

### 6.1 记忆分层（Agent 视角）

| 记忆 | 内容 | 生命周期 | 进入 Prompt 的方式 |
|------|------|---------|-------------------|
| **Dialog Memory** | 原始轮次列表 | 会话级 | 不直接进入；先摘要 |
| **Working Memory** | RouteIntent、候选、当前路线、pending_slots | 会话级 | 结构化注入 L2 |
| **Episodic Summary** | 每 3 轮自动生成的会话摘要 | 会话级 | 注入 L3 |
| **User Profile Snapshot** | 长期偏好压缩版 | 跨会话 | 注入 L2 固定段 |
| **Confirmed Facts** | 用户显式确认的事实（「就 200 预算」） | 会话级，高优先级 | 单独 bullet 列表，不可被摘要冲掉 |

### 6.2 结构化会话记忆模型

```
SessionState:
  session_id
  turn_count
  mode: "planning" | "replanning" | "clarifying" | "completed"

  route_intent: RouteIntent          # 累积意图（merge 结果）
  pending_slots: list[SlotName]      # 仍缺失的约束
  assumptions: list[Assumption]       # 系统做出的默认假设

  current_route: RoutePlan | null    # 当前生效路线
  confirmed_stop_ids: list[str]      # 用户锁定站点
  rejected_poi_ids: list[str]        # 用户明确拒绝

  dialog_summary: str                # 滚动摘要
  recent_turns: list[Turn]           # 仅保留最近 K 轮原文（K=4～6）

  run_artifacts:                      # 上次 Run 中间产物（供 Replan）
    last_candidate_pois: list[ref]
    last_template_id: str | null
```

**Turn 结构：**

```
Turn:
  turn_id
  user_utterance
  agent_response_type: "clarify" | "route" | "diff" | "multi_plan"
  agent_payload: structured JSON     # 非纯文本
  user_reaction: "accepted" | "revised" | "rejected" | null
```

### 6.3 上下文瘦身策略

LLM 上下文窗口有限，按以下顺序 **裁剪**（越靠后越先删）：

1. 删除：已过期 Run 的中间候选（只保留 top-10 ref）
2. 压缩：Dialog Memory → `dialog_summary`（保留 confirmed_facts 不压缩）
3. 压缩：POI 列表 → `{id, name, category, price, rating, one_line_ugc}` 表格
4. 压缩：UGC → 每 POI 最多 1 条代表评论
5. 删除：User Profile 中非本场景字段（如商务偏好对逛吃无效）
6. 保留：**confirmed_stop_ids、pending_slots、当前冲突说明** 永不删

**瘦身触发点：** 每次 LLM 调用前估算 token；超阈值则执行一轮压缩，并写 `compression_log` 供调试。

### 6.4 输出管理设计

Agent 对用户可见的输出分 **三层**，内部只维护结构化层：

```
Layer 1: Structured Output（系统真相源）
  RoutePlan / ClarifyQuestion / RouteDiff / MultiPlanResponse

Layer 2: Presentation Payload（给前端）
  stops[], map_deep_link, evidence[], relaxed_constraints[], diff_highlight[]

Layer 3: Natural Language Wrap（可选）
  简短开场 + 要点 bullet；由 render 节点生成，可关闭
```

**输出管理规则：**

| 场景 | 输出类型 | 必含字段 |
|------|---------|---------|
| 首次出路线 | `route` | stops, metadata, evidence_per_stop, assumptions |
| 澄清 | `clarify` | question, options[], pending_slot |
| 约束冲突 | `multi_plan` | plan_a, plan_b, tradeoff_explanation |
| Replan | `diff` | removed[], added[], rescheduled[], unchanged[] |
| 降级 | `degraded_route` | route + degraded_reasons[] |

**同一 Turn 禁止混出多种主类型**（不能既长篇澄清又在末尾塞完整路线），避免用户认知负担。

---

## 7. 会话状态与运行共建

### 7.1 「共建」的含义

用户与 Agent **共同构造** `SessionState`，而非 Agent 单方面生成：

```
用户 utterance ──merge──► RouteIntent
用户选 Plan B  ──write──► confirmed strategy
用户「第三家不去」──lock──► rejected_poi + replan trigger
用户「就按这个」──lock──► confirmed_stop_ids + mode=completed
```

每一轮结束后，状态机 **显式更新**，不依赖 LLM 隐式记住。

### 7.2 状态更新来源优先级

| 来源 | 写入字段 | 可信度 |
|------|---------|--------|
| 用户显式确认按钮 / 「就这个」 | confirmed_* | 最高 |
| 用户自然语言否定 | rejected_*, intent 覆盖 | 高 |
| LLM intent_merge 推断 | route_intent, pending_slots | 中（需校验） |
| User Profile 补全 | assumptions | 低（必须可展示、可推翻） |
| 工具事实 | validate 修正 | 高（营业/距离） |

### 7.3 状态机

```
                    ┌──────────────┐
         ┌─────────►│  INIT        │
         │          └──────┬───────┘
         │                 │ 首条输入
         │                 ▼
         │          ┌──────────────┐
         │   ┌─────►│ CLARIFYING   │◄────┐
         │   │      └──────┬───────┘     │ 仍缺 slot
         │   │             │ slots OK   │
         │   │             ▼            │
         │   │      ┌──────────────┐    │
         │   └──────│ PLANNING     │────┘
         │          └──────┬───────┘
         │                 │ 路线输出
         │                 ▼
         │          ┌──────────────┐
         └──────────│ REVIEWING    │  用户审阅路线
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              │ 确认        │ 修订        │ 重规划
              ▼            ▼            ▼
         COMPLETED    REPLANNING      PLANNING
```

- **REVIEWING**：默认停留态；用户任何修订意图 → **REPLANNING**。
- **COMPLETED**：可新开 Turn 但保留 Session 内 Profile 学习结果。

### 7.4 Run 与 Session 的共建产物

单次 Run 结束后，以下产物 **选择性沉淀** 到 Session：

| 产物 | 是否沉淀 | 说明 |
|------|---------|------|
| route_intent | 是 | merge 后的最新版 |
| current_route | 是 | 替换旧路线 |
| candidate_pois 全量 | 否 | 只留 ref top-10 |
| 工具原始返回 | 否 | 只留 validate 结论 |
| clarify 问题 | 是 | 避免重复问同一 slot |
| assumptions | 是 | 直到用户否定 |

---

## 8. 回复机制设计

### 8.1 回复类型与触发

| 类型 | 触发 | 用户感知 |
|------|------|---------|
| **ClarifyReply** | pending_slots 非空 | 一个问题 + 可点选项 |
| **RouteReply** | Plan Run 成功 | 完整行程 + 地图 + 依据 |
| **MultiPlanReply** | 约束冲突 | 两套方案 + 权衡说明 |
| **DiffReply** | Replan 成功 | 「保留了 X，替换了 Y，预计多 20 分钟」 |
| **AssumedRouteReply** | Clarify 达上限 | 路线 + 黄色假设标签 |
| **DegradedReply** | 工具/LLM 降级 | 部分结果 + 原因 + 重试建议 |
| **RejectReply** | 非出行意图 | 礼貌拒绝 + 能力说明 |

### 8.2 回复组成结构

统一回复 envelope：

```
AgentReply:
  reply_type: enum
  session_id
  turn_id

  structured: {...}           # Layer 1，前端/地图必用

  presentation:
    title: str
    summary: str              # 一句话
    highlights: list[str]      # 最多 5 条
    actions: list[Action]      # 「确认」「换方案」「继续改」

  meta:
    assumptions: list
    relaxed_constraints: list
    degraded: bool
    next_suggested_user_moves: list[str]   # 「你可以说：换一家日料」
```

### 8.3 流式回复节奏（体验层）

即使用户看到「打字机效果」，**语义块**仍应按阶段推送：

```
phase: understanding   → 「我理解你想在徐汇逛吃约 3 小时…」
phase: retrieving      → 「正在找符合条件的店…」
phase: optimizing      → 「正在排路线顺序…」
phase: complete        → 结构化 RouteReply（非逐字 token 拼 JSON）
```

**禁止**：流式输出半个 JSON 让用户看到 `{ "stops": [`。

结构化结果 **整包就绪后一次交付**；流式只用于 **进度 narration**（可选）或 **非结构化说明文字**。

### 8.4 确认与修订的回复闭环

```
Agent 输出 RouteReply
    │
    ├─ 用户：「就这个」→ ConfirmReply（状态 → COMPLETED）+ 可选反馈邀请
    │
    ├─ 用户：「第二家换日料」→ 进入 Replanning → DiffReply
    │
    ├─ 用户：「预算是 150 不是 200」→ intent_merge → 可能 Clarify 或 Replan
    │
    └─ 用户：30min 无响应 → SoftConfirmReply（「当前路线是否 OK？」）
```

### 8.5 错误与恢复的回复

| 失败 | 用户可见 | 内部 |
|------|---------|------|
| intent 解析失败 | 「我没听清预算还是区域，能再说一下吗？」 | 重试 shrink schema |
| 检索为空 | 「该区域没有符合的店，要放宽预算还是换区域？」 | Clarify |
| 校验不可行 | MultiPlanReply | 不抛 stack trace |
| LLM 超时 | DegradedReply（模板路线） | degraded=true |

**对用户永远输出「下一步可说什么」**，降低决策负担——这与赛题目标一致。

---

## 9. 跨维度协同示例

**场景：三轮对话完成规划并修订**

| Turn | 用户 | Turn Orchestrator | Run | 工具 | 回复 |
|------|------|-------------------|-----|------|------|
| 1 | 「徐汇逛吃」 | → Clarify | 无 Plan Run | 无 | ClarifyReply：预算？ |
| 2 | 「200 以内 3 小时」 | → Plan | 全 pipeline | POI+UGC+optimize | RouteReply：3 站 |
| 3 | 「第二家换日料」 | → Replan | partial | 替换检索+local_optimize | DiffReply：1 站替换 |

**状态共建轨迹：**

- Turn 1 后：`pending_slots=[budget]`，`route_intent.district=徐汇`
- Turn 2 后：`current_route` 填充，`mode=REVIEWING`
- Turn 3 后：`confirmed_stop_ids=[站1,站3]`，站 2 替换，`dialog_summary` 更新

---

## 10. 设计检查清单

实现 Agent 运行时前，应用本文档自检：

- [ ] 主循环是否区分 Turn 调度与 Run 编排？
- [ ] Clarify 是否禁止重检索/全量生成？
- [ ] Replan 是否锁定 confirmed stops？
- [ ] 工具是否分「编排器必调」与「LLM 自选审批」？
- [ ] Prompt 是否四层分离且 L2/L3 可压缩？
- [ ] 会话记忆是否有结构化 SessionState，而非仅 messages 堆叠？
- [ ] 输出是否 Layer1 结构化 + Layer2 展示分离？
- [ ] 回复是否有统一 AgentReply envelope？
- [ ] 流式是否只用于进度/叙述，JSON 整包交付？
- [ ] 每个失败路径是否映射到可执行的下一步用户话术？

---

## 11. 与工程文档的边界

| 本文档（Agent 运行时） | 工程 README |
|----------------------|-------------|
| 主循环、模式、状态机 | API 路由、MQ、Worker |
| 工具语义与调用策略 | 工具 SDK、连接池 |
| Prompt 分层与 Agent 缓存 | Redis、LLM Gateway |
| SessionState 字段语义 | PostgreSQL 表结构 |
| 回复类型与流式节奏 | SSE 协议、K8s |

两者通过 **`session_id` / `turn_id` / `RoutePlan` schema** 对齐，但设计阶段应分开思考，避免用「加 Redis」代替「会话记忆模型没想清楚」。
