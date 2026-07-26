# GenTrip Agent 自动化测试计划

## 1. 目标与原则

目标不是只验证接口返回 `200`，而是持续证明以下事实：

1. Agent 正确理解显式约束，并让它们在 Plan、Replan 和热缓存路径中保持有效。
2. 输出路线真实可执行，不把降级或不可行方案描述为成功。
3. 运行时在重试、取消、超时、并发和依赖故障下有确定的终态，且不串租户、不丢会话。
4. 模型、Prompt、POI 数据和排序策略改变时，质量回归可以量化、定位并阻断发布。

测试按成本分层：PR 只运行确定性、无网络、低成本测试；每日运行 Compose 和回放集；每周运行固定模型的离线 LLM judge、数据质量与压力测试。任何线上 LLM 都不进入 PR 阻断门禁。

## 2. 当前基线与缺口

已有能力：

| 资产 | 当前内容 | 价值 |
| --- | --- | --- |
| 约束 golden | `golden_constraint_cases.json`，22 个语言变体 | 验证规则提取、默认值和记忆继承 |
| 多轮 golden | `golden_conversations.json`，8 个会话/16 轮 | 验证 Plan/Replan、diff 与路线质量 |
| 质量函数 | `route_quality` | 预算、时间、排队、重复 POI、偏好覆盖、路线节奏 |
| 运行时 E2E | `test_runtime_e2e_quality.py` | 入队、worker、事件、checkpoint、终态 |
| 故障测试 | timeout、重试/DLQ、CAS、容量 | 验证部分可靠性边界 |

缺口：真实 Redis/Postgres Compose E2E 还不是必跑门禁；没有可回放的 LLM 契约集；缺少 retrieval recall 与 POI 数据漂移检测；没有 property/metamorphic 测试、并发/长稳压测、评测报告存档和基线回归判定；主观体验尚无固定 judge/human review 闭环。

## 3. 评测资产模型

所有测试 case 采用版本化 JSONL，保存到 `backend/fixtures/evals/<suite>/<version>.jsonl`。每个 case 至少包含：

```json
{
  "id": "replan-delete-add-001",
  "risk": "high",
  "tags": ["replan", "exclusion", "memory"],
  "fixture_version": "poi-2026-07-26",
  "turns": [{"query": "...", "expect": {"hard": {}, "quality": {}}}],
  "seed": 42,
  "owner": "planner"
}
```

硬断言和质量断言必须分开。硬断言包括：意图/模式、显式预算、时间、排除项、确认站点、租户隔离、终态和 response schema。质量断言包括：路线可行性、偏好覆盖、总耗时、最大单段交通、排队、预算利用率、POI 多样性和解释完整度。

每个 case 还应记录来源：真实匿名失败样本、产品需求、历史回归或合成边界样本。修复线上问题时，先新增一个会失败的 case，再修复代码。

## 4. 测试分层与准入标准

| 层级 | 覆盖对象 | 实现方式 | 运行频率 | 阻断条件 |
| --- | --- | --- | --- | --- |
| L0 单元/契约 | 节点、schema、Prompt 输出解析、工具适配 | pytest + fake LLM/tool | 每个 PR | 任一失败 |
| L1 语义与路线 golden | Plan/Replan、记忆、路线质量 | 版本化 fixtures + 固定 seed | 每个 PR | 任一 hard violation；质量分低于 case 阈值 |
| L2 变形/性质测试 | 等价表达、约束单调性、不可变项 | Hypothesis 或生成式 fixture | 每个 PR | 发现反例 |
| L3 运行时集成 | FastAPI + Redis Streams + Postgres + worker + SSE | `docker compose` 独立 test project | 每日和合并前 | 终态、事件顺序、持久化、隔离不符合 |
| L4 故障注入 | LLM、工具、Redis、Postgres、worker、超时 | 可控 fake/容器重启 | 每日 | 不满足恢复或安全终态 |
| L5 离线体验评审 | 路线与说明的软偏好 | 固定模型/Prompt judge + 人工抽检 | 每周/发布前 | 指标显著回归或高风险 disagreement |
| L6 性能与容量 | 排队、并发、尾延迟、资源 | k6/Locust + Compose | 每周/发布前 | SLO 不达标 |

### L0: 节点与模型契约

- 为所有 LLM 节点维护录制回复集：成功、空 JSON、字段缺失、未知枚举、超长输出、429、超时、500、内容不安全。
- 断言每个节点只接受 schema 合法输出；异常必须进入明确的 `fallback`、`degraded` 或 `failed` 状态。
- 对 `constraint_extract`、`turn_orchestrate`、`replan_parse` 做 token-level/phrase-level 回归；对 `route_present` 做结构化字段和禁止虚假成功声明断言。
- 对每一个 tool 定义 contract test：输入 schema、超时、幂等、错误映射、来源标识、缓存命中/失效。

### L1: Golden 数据扩展

将当前 8 会话扩展至 120 个会话、300-400 轮；约束语言集扩展至 250 条。按风险配额而不是只按业务类别采样：

| 主题 | 首批目标 | 必测边界 |
| --- | ---: | --- |
| Plan 约束组合 | 80 | 预算/时间/排队/起止时间/地点/人数/多类别/排除项冲突 |
| Replan 原子修改 | 80 | 增删改替换、序号歧义、类别与菜系、锁定站、不可行回滚 |
| 记忆与画像 | 40 | 继承、显式覆盖、过期、拒绝 POI、跨会话与跨租户隔离 |
| 澄清/不可行/拒绝 | 30 | 不安全默认、检索为空、非旅行输入、冲突约束 |
| 热路径与缓存 | 20 | 精确命中、相似命中、失效、不同显式约束不得复用 |
| 安全与认证 | 20 | JWT 撤销、越权读写、会话删除、重放和 idempotency |

黄金集不得断言偶然排序或单一 POI，除非该 POI 是产品承诺。优先断言可观察的类别、硬约束、质量区间、diff 语义和来源。

### L2: Metamorphic 与性质测试

此层专门捕捉“样本没覆盖但逻辑应恒成立”的错误：

1. 同义表达不变性：`下午两点`、`14:00`、`两点出发` 得到等价时间约束。
2. 约束单调性：降低预算、缩短时间、增加排除项后，结果不能新增违反该约束的路线。
3. 显式优先级：本轮显式输入必须覆盖 profile、历史和默认 assumptions。
4. Replan 局部性：只删除咖啡不能删除未冲突的锁定站；失败时原路线的 `current_route` 不变。
5. 幂等性：相同 `idempotency_key` 不创建第二个 run；重放不会重复写入 turn。
6. 租户隔离：任意 tenant A 的 session/run/profile/Redis key 永不出现在 tenant B 的响应中。

### L3: 真实运行时 E2E

新增 `pytest -m runtime_integration` 专用 Compose profile，测试启动独立 Postgres、Redis、API、worker，禁用真实 LLM、使用稳定 POI fixture。测试至少覆盖：

1. HTTP `POST /routes/plan/runs` 到 SSE 完成事件和 `GET run` 最终结果。
2. Redis pending 消息在 worker kill/restart 后被 reclaim，且最终仅产生一个有效 turn。
3. checkpoint 顺序与 `phase_log` 一致；取消、超时、DLQ 都产生正确终态和 error code。
4. 两个租户并发使用相同 `session_id` 时，数据和事件完全隔离。
5. 数据库重启后的 session、turn、run、审计与 checkpoint 可恢复。

### L4: 故障注入矩阵

| 依赖/事件 | 注入 | 必须断言 |
| --- | --- | --- |
| LLM | 429、5xx、慢响应、无效 JSON | 有界重试；规则 fallback 或可解释失败；无 prompt 泄漏 |
| POI/交通工具 | 空结果、部分结果、超时、陈旧数据 | 不伪造路线；标识 degraded/source；可行时走 fallback |
| Redis | enqueue 失败、worker kill、pending、DLQ replay | 503 或幂等恢复；无重复提交 |
| Postgres | 写入失败、连接中断、CAS 冲突 | 不覆盖新会话；终态可追踪；重试安全 |
| 用户行为 | cancel 与新请求竞争 | 旧 run 取消且不能覆盖新 run |
| 容量 | 超过 tenant active-run 限制 | 429；同 session 替换仍可用 |

故障测试不得只验证异常被抛出；必须验证数据库 run、事件流、session 状态和用户 API 响应四个观察面一致。

### L5: 离线 LLM-as-Judge 与人工复核

固定一个 judge 模型、版本化 Prompt 和 JSON rubric，不参与 PR 通过与否。输入为冻结的 query、memory、candidate POI、route 和 presentation，输出 1-5 分及理由：偏好匹配、路线节奏、解释诚实、assumption 披露、replan diff 清晰度。

每周运行：

- 全量 judge，生成按 Prompt/模型/POI fixture 版本分组的报告。
- 对分数下降超过 0.2、judge 与规则冲突、或高风险 case 抽样 20% 人工复核。
- 记录人工最终标签，计算 judge 与人工的一致率；一致率低于 0.75 时仅修正 judge，不以其阻断发布。

## 5. 指标与门禁

硬约束是零容忍：显式排除、预算、`return_by`、已确认站点、租户边界、权限和重复副作用，任一违反即失败。

软质量采用基线回归，不使用一次性主观阈值：

| 指标 | PR 门禁 | 每日/发布门禁 |
| --- | --- | --- |
| Golden hard pass rate | 100% | 100% |
| 质量 expectation score | 每 case 不下降 | P50/P90 不低于冻结基线 1 分 |
| 约束提取 F1 | >= 0.99 | >= 0.99，按字段分组报告 |
| Replan 原子提交率 | 100% | >= 99.5% |
| LLM fallback 语义正确率 | >= 99% | >= 99% |
| E2E run 成功率 | 不适用 | >= 99%（稳定依赖环境） |
| P95 总 run 延迟 | 不适用 | mock <= 3s；真实模型单独设预算 |
| tenant 数据泄漏 | 0 | 0 |

基线更新必须由评测负责人审核，附带 case 变化、POI 版本、模型/Prompt 版本和 diff 报告；不能因测试失败直接降低阈值。

## 6. CI/CD 编排

1. **PR Required**：格式/类型检查、L0、L1、L2；输出 JUnit 与 `eval-summary.json`。
2. **Merge Queue**：全量 pytest，加上 Compose 的关键 L3 E2E。
3. **Nightly**：完整 L3/L4、数据质量、LLM replay、全 golden、覆盖率与 mutation smoke。
4. **Weekly**：L5 judge、L6 负载与 30 分钟 soak、POI 数据漂移报告。
5. **Release Candidate**：冻结所有 fixture/model/prompt 版本，执行全套，并把报告、trace dashboard snapshot 和失败样本附到发布记录。

每次评测输出 `artifacts/evals/<run_id>/`：`summary.json`、case 结果 JSONL、失败输入最小复现、运行 trace id、版本清单、JUnit 和 HTML 汇总。不得在 artifact 写入 API key、原始认证 token 或完整用户私密对话。

## 7. 实施路线

### Phase A，1 周：让现有测试成为可靠门禁

- 建立 CI workflow 和 pytest markers：`unit`、`golden`、`runtime_integration`、`fault`、`llm_replay`、`load`。
- 将 golden fixture 加入 schema 校验和版本字段；生成机器可读 `eval-summary.json`。
- 先补 30 个高风险 case：显式排除、时间、排队、删除加站组合、记忆覆盖、非旅行拒绝。

验收：PR 可见分层结果；现有 212 测试、golden 与 E2E 全部稳定重复三次。

### Phase B，2 周：真实持久化与故障测试

- 加 Compose E2E profile 和测试数据库/Redis namespace 隔离。
- 实现上述 L3/L4 五条核心场景，特别是 worker crash reclaim、CAS 竞争与 DLQ replay。
- 接入覆盖率与 mutation smoke，优先关键决策函数：turn routing、constraint merge、RouteJudge、replan commit。

验收：故障矩阵每类至少一个端到端 case；错误终态、checkpoint、事件和 session 一致。

### Phase C，2 周：质量数据与回归分析

- 扩充至首批 120 会话/300+ 轮和 250 条语言约束 case。
- 建立 POI retrieval 标注集：每 query 标注 `must_recall`、`acceptable_categories`、`forbidden`，报告 Recall@K、NDCG@K、空召回率。
- 建立 baseline 存储和 PR diff 报告。

验收：每次 POI、Prompt、模型或排序变更都能显示质量增减及受影响 case。

### Phase D，持续：体验与容量

- 运行固定 judge/human review 闭环。
- 建立 k6/Locust 场景：稳定并发、突发、热点会话争抢、多租户公平性、慢 LLM、worker 滚动重启。
- 依据实测设置 P95、队列深度、DLQ 增长、token 成本和容量阈值告警。

## 8. 责任与退出条件

Planner owner 维护 golden 和质量规则；Runtime owner 维护 L3/L4 和 SLO；Data owner 维护 POI retrieval 集；产品/运营每周复核高风险 judge disagreement。任一新节点、Prompt、工具或数据源必须同时增加对应 L0 contract、至少一个 L1/E2E case 和可观测字段。

计划完成的退出条件是：PR、每日、每周三条测试流水线可运行；测试资产与版本可追溯；硬约束、可靠性和数据隔离得到自动验证；质量回归能够量化而非依赖人工肉眼发现。
