# GenTrip 本地性能测试报告（2026-08-09）

## 1. 结论

本轮测试验证了 GenTrip 在关闭 LLM、关闭鉴权、使用 mock 交通估算时的本地异步规划容量，并用真实 DeepSeek 补充了 1 路和 3 路小流量测试。测试覆盖 smoke、1/2/4 Worker 扩展性、5 分钟持续负载、300 并发突发、同租户限流和 10 分钟稳定性，共产生 17,757 个成功终态的测试 Plan Run。

主要结果：

- 300 并发突发下，600/600 个任务成功，API 提交 P95 为 406 ms，数据库端端到端 P95 为 14.854 s。
- 4 Worker、100 用户、5 分钟持续负载下，4,886/4,886 个任务成功，吞吐 16.29 plans/s，数据库端端到端 P95 为 8.017 s。
- 4 Worker、50 用户、10 分钟稳定性负载下，8,742/8,742 个任务最终成功，吞吐 14.57 plans/s，数据库端端到端 P95 为 5.091 s。
- 1/2/4 Worker 的 120 秒对照吞吐分别为 5.88、9.68、13.73 plans/s；4 Worker 相对 1 Worker 提升 2.33 倍，但扩展效率下降到约 58%。
- 主要业务延迟来自 Redis 队列等待，而不是单次图执行。4 Worker 稳定负载中的执行 P95 约 0.39 s，排队 P95 为 4.79-7.74 s。
- 10 分钟测试期间一个 Worker 因一次 Redis QueueUnavailable 退出，且没有自动重启。剩余三个 Worker 完成了全部任务，但该轮不满足“4 Worker 全程健康”的稳定性验收。
- Redis 主任务 Stream 保留了 18,788 条已消费消息，PostgreSQL 累积到约 1.24 GB 和 443,011 个 run event，当前缺少明确的数据保留和清理策略。
- 真实 DeepSeek 单请求客户端端到端耗时 39.05 s；3 路并发全部成功，但平均延迟增至 64.18 s，P95 为 87.42 s，说明供应商并发下延迟明显上升。

因此，当前结果证明的是“本地确定性运行时具有约 14-16 plans/s 的持续处理能力，真实 DeepSeek 1-3 路小流量可完成但延迟较高”，不能外推为 JWT 多租户或生产多副本容量。

## 2. 被测环境

| 项目 | 配置 |
| --- | --- |
| Git commit | `9abde4dc6af1d4cdba06c913322734c14e542fbb` |
| 工作树 | Dirty，测试针对当前未提交工作树，不能只依靠 commit 复现 |
| CPU | Intel Core Ultra 7 155H，16 核 / 22 逻辑处理器 |
| 主机内存 | 31.6 GB |
| Docker 配额 | 22 CPU，15.4 GiB |
| JMeter | 5.6.3，非 GUI 模式 |
| Java | 1.8.0_92 |
| API | FastAPI，`http://127.0.0.1:8080` |
| 队列 | Redis Streams consumer group |
| 存储 | PostgreSQL 16 + PostGIS |
| 交通估算 | mock |
| LLM | 容量测试关闭；真实模型 smoke 单独启用 |
| 鉴权 | 容量测试关闭；同租户限流单独验证 |

每个 JMeter 线程默认使用独立 tenant，并从 10 条中文约束查询中循环取值。测试流程为提交异步 Plan Run、每 500 ms 轮询状态，直到 `completed/degraded` 或失败终态。

## 3. 测试结果

### 3.1 Worker 扩展性

固定 50 个闭环用户、10 秒 ramp-up、120 秒持续时间。JMeter 截止时中断的在途轮询不计为后端失败；测试后等待数据库全部进入终态。

| Worker | 最终任务数 | 成功率 | 吞吐 | DB E2E 平均 | DB E2E P95 | 排队 P95 | 执行 P95 | 相对 1W |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 706 | 100% | 5.88/s | 8.161 s | 11.395 s | 11.195 s | 0.256 s | 1.00x |
| 2 | 1,162 | 100% | 9.68/s | 4.726 s | 5.519 s | 5.278 s | 0.273 s | 1.65x |
| 4 | 1,647 | 100% | 13.73/s | 3.215 s | 3.917 s | 3.626 s | 0.393 s | 2.33x |

扩容有效，但不是线性的。Worker 增加后 PostgreSQL CPU 明显升高，4 Worker 对照中 PostgreSQL 平均 CPU 约 172%，峰值约 296%。

### 3.2 五分钟持续负载

配置：4 Worker、100 用户、30 秒 ramp-up、300 秒负载。

| 指标 | 结果 |
| --- | ---: |
| 最终任务 | 4,886 |
| 最终成功率 | 100% |
| 持续吞吐 | 16.29 plans/s |
| API 提交 P95 | 110 ms |
| DB E2E 平均 | 5.600 s |
| DB E2E P95 | 8.017 s |
| DB E2E P99 | 13.693 s |
| 排队 P95 | 7.736 s |
| Worker 执行 P95 | 0.389 s |
| 测试结束 Redis pending | 0 |

HTML 报告：[5 分钟持续负载](../loadtest/results/20260809-152326-soak-w4-u100-300s/html/index.html)

### 3.3 300 并发突发

配置：4 Worker、300 用户、15 秒 ramp-up、每线程 2 次，共 600 次规划。

| 指标 | 结果 |
| --- | ---: |
| 最终任务 | 600 |
| 最终成功率 | 100% |
| 完成窗口 | 43.314 s |
| API 提交平均 | 128.2 ms |
| API 提交 P95 | 406 ms |
| API 提交 P99 | 487 ms |
| DB E2E 平均 | 10.172 s |
| DB E2E P95 | 14.854 s |
| DB E2E P99 | 15.206 s |
| 排队 P95 | 14.614 s |
| Worker 执行 P95 | 0.389 s |

HTML 报告：[300 并发突发](../loadtest/results/20260809-153008-spike-w4-u300-600runs/html/index.html)

### 3.4 同租户并发保护

配置：4 Worker、20 个线程共享一个 tenant、1 秒 ramp-up。

- 9 个任务在测试过程中被接受并最终成功。
- 11 个请求返回 HTTP 429。
- 限制是“同时 active run 最大 3 个”，不是“整个测试最多接受 3 个”；前序任务完成后可以继续接受新任务。

该结果证明并发压力下租户 active-run 限制生效。HTML 报告：[同租户限流](../loadtest/results/20260809-153205-tenant-limit-w4-u20/html/index.html)

### 3.5 十分钟稳定性负载

配置：预期 4 Worker、50 用户、30 秒 ramp-up、600 秒负载。

| 指标 | 结果 |
| --- | ---: |
| 最终任务 | 8,742 |
| 最终成功率 | 100% |
| 吞吐 | 14.57 plans/s |
| API 提交 P95 | 78 ms |
| DB E2E 平均 | 3.068 s |
| DB E2E P95 | 5.091 s |
| DB E2E P99 | 6.185 s |
| 排队 P95 | 4.791 s |
| Worker 执行 P95 | 0.392 s |
| Redis pending | 0 |

`worker-2` 在测试约 5 分 36 秒时输出 `plan worker queue unavailable: unable to read plan queue` 并以状态码 1 退出。Compose restart policy 为 `no`，因此后半段实际由 3 个 Worker 完成。HTML 报告：[10 分钟稳定性负载](../loadtest/results/20260809-153441-endurance-w4-u50-600s/html/index.html)

### 3.6 真实 DeepSeek 小流量

真实模型测试使用独立 Compose override，只关闭鉴权，不清空模型 key。未记录或输出 key 内容。

| 场景 | 结果 | 客户端 E2E | DB 执行 | LLM 调用 | Token |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 Worker / 1 用户 | 1/1 成功 | 39.05 s | 36.60 s | 4 | 3,840 |
| 3 Worker / 3 用户 | 3/3 成功 | 平均 64.18 s，P95 87.42 s | 48.75-84.94 s | 4-5/任务 | 合计 24,800 |

3 路并发测试中数据库排队仅 0.031-0.037 s，因此延迟增长主要发生在模型调用和完整 Agent 执行阶段。日志中没有 429、timeout 或模型异常。总计消耗 28,640 tokens。

HTML 报告：[单路真实 LLM](../loadtest/results/20260809-155346-llm-live-w1-u1/html/index.html)、[三路真实 LLM](../loadtest/results/20260809-155530-llm-live-w3-u3/html/index.html)。样本数很小，该结果用于连通性和延迟趋势判断，不用于声明供应商容量上限。

### 3.7 SSE 客户端可见延迟

测量路径与前端一致：先 `POST /routes/plan/runs`，随后连接 `GET /routes/plan/runs/{run_id}/events`。确定性模式采样 20 次，真实 LLM 模式采样 1 次。

| 指标 | 确定性模式 P50 | 确定性模式 P95 | 真实 LLM 单样本 |
| --- | ---: | ---: | ---: |
| POST 提交 | 17.88 ms | 38.64 ms | 41.55 ms |
| SSE 响应头建立 | 3.88 ms | 4.62 ms | 9.80 ms |
| 提交到首个事件 | 22.46 ms | 43.11 ms | 52.52 ms |
| 订阅后到首个事件 | 4.10 ms | 4.97 ms | 10.96 ms |
| 提交到首个 completed phase | 276.76 ms | 296.16 ms | 2.83 s |
| 提交到最终 complete | 278.24 ms | 297.20 ms | 52.53 s |

持久化 phase event 从服务端时间戳到客户端接收的平均延迟 P95 为 214.21 ms，20 个样本中的单事件最大值为 255.92 ms。该结果与服务端每 250 ms 查询一次新事件的实现一致。

结论：SSE 本身可以在提交后约 20-50 ms 给前端首个运行状态，主要观测延迟是持久化事件轮询带来的约 0-250 ms。真实 LLM 的最终 52.53 s 不是 SSE 传输延迟，而是模型和 Agent 节点执行时间。当前 LLM 调用是完整响应模式，SSE 传输的是节点状态与节点结果，不是逐 token 输出。

原始结果：[确定性 SSE](../loadtest/results/20260809-sse-latency/deterministic.json)、[真实 LLM SSE](../loadtest/results/20260809-sse-latency/llm-live.json)。复测脚本为 `scripts/measure_sse_latency.py`。

## 4. 资源观测

| 场景 | API CPU 平均/峰值 | Worker CPU 合计平均/峰值 | PostgreSQL CPU 平均/峰值 | Redis CPU 平均/峰值 |
| --- | --- | --- | --- | --- |
| 1W / 50U | 19.9% / 50.2% | 46.0% / 58.0% | 55.1% / 125.2% | 3.3% / 5.6% |
| 2W / 50U | 26.5% / 57.0% | 95.9% / 118.7% | 97.1% / 189.4% | 5.0% / 9.6% |
| 4W / 50U | 37.1% / 80.6% | 175.2% / 217.6% | 172.1% / 295.9% | 8.2% / 13.3% |
| 4W / 100U / 5m | 45.7% / 86.8% | 178.9% / 246.3% | 184.3% / 295.1% | 8.3% / 11.5% |
| 4W / 300U spike | 51.5% / 84.7% | 146.4% / 205.6% | 151.6% / 275.9% | 6.8% / 9.1% |

十分钟测试中：

- API 内存首尾窗口约 93.8 MiB -> 95.1 MiB，基本稳定。
- Worker 内存处于约 249-296 MiB/实例；没有发现所有实例同步单调增长，但一个 Worker 中途退出。
- PostgreSQL 内存首尾窗口约 817.8 MiB -> 1,224.9 MiB。
- Redis 内存首尾窗口约 244.5 MiB -> 429.2 MiB。

PostgreSQL/Redis 增长与测试写入 8,742 个 run、会话、turn 和大量 phase event 同时发生，不能仅凭该曲线认定内存泄漏。但数据保留没有上限，会造成确定性的容量增长。

## 5. 关键问题与优先级

### P0：Worker 遇到瞬时 Redis 读取异常直接退出

当前 `run_worker()` 没有捕获主循环中的 QueueUnavailable，`main()` 直接结束进程；Compose 也没有 restart policy。应同时完成：

1. Worker 主循环对 Redis 读取异常执行带抖动的指数退避并持续重试。
2. 记录原始异常类型，当前 SystemExit 只保留了统一错误文案，无法定位是 timeout、connection reset 还是其他异常。
3. Compose 本地/生产配置增加 `restart: unless-stopped` 或由 Kubernetes restart policy 托管。
4. 增加 `worker_up`、重连次数和消费者数量告警；压测门禁校验测试结束时 Worker 数量未减少。

### P0：Redis Stream 和运行事件无限增长

ACK 只会清除 pending，不会删除 Stream entry。当前主 Stream 已达到 18,788 条，数据库 run event 达到 443,011 条。应定义：

- Redis Stream 按已完成消息 ID 或安全时间窗口执行 `XTRIM MINID`，保留最近 24-72 小时用于恢复。
- DLQ 单独保留更长时间，不与主 Stream 使用相同策略。
- run event、测试 tenant、trace 和 checkpoint 设置分层 TTL/归档任务。
- 压测结束自动删除 `perf-*` tenant 的会话和运行数据，避免污染长期数据库。

### P1：PostgreSQL 是扩容后的主要共享瓶颈

4 Worker 时 PostgreSQL CPU 已显著高于 API 和 Redis。下一步应先启用 `pg_stat_statements`，定位 runs、sessions、run_events 和 POI 查询的写入/查询成本，再决定批量写 event、降低轮询写放大、调整连接池或增加索引；不应直接盲目增加到 8 Worker。

### P1：客户端轮询放大 API 读流量

每个 active run 每 500 ms 轮询一次。高并发下状态查询量远高于规划提交量。生产前端应优先使用 SSE，轮询作为降级路径，并采用 500 ms -> 1 s -> 2 s 的退避策略。

### P1：LLM 开关存在隐式自动启用

正常容器中 `LLM_ENABLED=false`，但非标准环境变量 `deepseek-v4-pro` 存在时，配置层会自动将 LLM 改为启用。这会使部署人员误判费用和数据外发行为。应迁移到单一标准 key 名，要求 `LLM_ENABLED=true` 与 key 同时满足才启用，并在迁移期只对旧变量发出不包含值的弃用告警。

## 6. 未覆盖范围

- 没有多租户 JWT token 池，未执行带完整认证和授权的系统总容量测试。
- 真实 LLM 只执行 1 路和 3 路共 4 个 Plan，没有执行持续或高并发模型压测，以控制费用和供应商风险。
- 本测试衡量完整响应延迟，非流式模型无法测量真实 LLM TTFT。
- 10 分钟测试不是 1 小时或 24 小时生产级长稳。
- 性能成功不等于路线质量正确；本轮没有把 Golden Set/Route Judge 作为负载中的质量门禁。
- 没有执行 Redis/PostgreSQL 故障注入和 Worker kill/reclaim 验收。

## 7. 复现入口

压测脚本现在会为每轮生成：

- `run-manifest.json`：Git、机器、Docker、参数和 Worker 数。
- `summary.json`：任务计数、P95/P99、截止时在途数和 Worker 存活门禁。
- `docker-stats.csv`：每两秒的容器 CPU、内存和 IO。
- `results.jtl` 与 `html/index.html`：JMeter 原始结果和 Dashboard。

入口脚本为 `scripts/run-jmeter.ps1`。大规模测试必须继续使用 `loadtest/docker-compose.loadtest.yml`，避免误调用真实 LLM。
