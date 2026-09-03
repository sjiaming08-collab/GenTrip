# GenTrip JMeter 压测

这套场景针对 GenTrip 的异步运行链路：

1. `POST /api/v1/routes/plan/runs` 提交任务并提取 `run_id`。
2. 每 500 ms 查询 `GET /api/v1/routes/plan/runs/{run_id}`。
3. 等待 `completed` 或 `degraded`，失败、取消、超时和中断均计为失败。
4. 分别统计提交延迟和包含排队、Worker、LLM 在内的端到端延迟。

## 前置条件

- GenTrip API 可通过 `http://127.0.0.1:8080/api/v1/health` 访问。
- 安装 JDK 17，并确保 `java -version` 生效。
- 从 Apache JMeter 官网下载并解压 JMeter 5.6+，设置：

```powershell
$env:JMETER_HOME = "C:\tools\apache-jmeter-5.6.3"
& "$env:JMETER_HOME\bin\jmeter.bat" -v
```

若后端 `AUTH_ENABLED=true`，先登录并只把凭据保存在当前 PowerShell 进程的环境变量中：

```powershell
$login = Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8080/api/v1/auth/login" `
  -ContentType "application/json" `
  -Body (@{ email = "你的邮箱"; password = "你的密码" } | ConvertTo-Json)
$env:GENTRIP_JWT = $login.access_token
$env:GENTRIP_TENANT_ID = $login.tenant.tenant_id
```

JMX 会从环境变量读取 token，不会把它写入文件或报告。关闭当前终端即可清除这两个临时变量；也可以执行 `Remove-Item Env:GENTRIP_JWT, Env:GENTRIP_TENANT_ID`。

## 执行

从仓库根目录运行。先进行单用户 smoke test：

```powershell
.\scripts\run-jmeter.ps1 -Users 1 -Loops 1 -RampSeconds 1 -DurationSeconds 180
```

当前 Compose 只有一个 Worker。测试 3 个并发且启用真实 LLM 时，应给排队留出更长观测窗口：

```powershell
.\scripts\run-jmeter.ps1 -Users 3 -Loops 1 -RampSeconds 3 -DurationSeconds 600 -MaxPolls 900
```

再执行基线测试：

```powershell
.\scripts\run-jmeter.ps1 -Users 5 -RampSeconds 30 -DurationSeconds 600
.\scripts\run-jmeter.ps1 -Users 10 -RampSeconds 60 -DurationSeconds 600
.\scripts\run-jmeter.ps1 -Users 25 -RampSeconds 120 -DurationSeconds 1800
```

每次结果写入新的 `loadtest/results/<timestamp>/`，HTML 报告入口为 `html/index.html`。

## 指标解释

- `Submit plan - acceptance`：API 接收请求并写入运行队列的耗时，只接受 HTTP 202。
- `Poll plan status`：单次状态查询耗时，不代表规划耗时。
- `E2E plan completion`：从提交到终态的总耗时，是主要业务延迟指标。
- `Assert successful terminal status`：`completed/degraded` 成功，其余终态或轮询耗尽失败。

重点查看 HTML Dashboard 的 Error %、Throughput、p90、p95、p99，并同时观察 Grafana 中 API、Worker、Redis、Postgres、LLM 和队列积压指标。

## 测试边界

- 默认每个 JMeter 线程使用独立 tenant，测试系统总吞吐。若所有线程共用 tenant，本项目默认每租户最多 3 个 active run，出现 429 是限流生效，不代表系统崩溃。
- JWT 模式下，一个 token 绑定一个 tenant，因此单 token 测试应先控制在 1-3 个用户。系统总容量测试需要准备多个测试 tenant/token，或在隔离的压测环境关闭鉴权后使用脚本生成的独立 tenant；不要在生产环境绕过鉴权。
- 大并发测试建议 `LLM_ENABLED=false`，用于验证 API、Redis Streams、Worker、Postgres 和规划图。真实 LLM 只做 1-5 并发的小流量测试，避免供应商限流和不可控费用。
- 当前模型调用是非流式的，因此该场景不能得到真实 LLM 首 token 延迟；它测量的是请求接收和完整规划完成时间。
- 不要在 JMeter GUI 中做正式压测。GUI 只用于调试 JMX，正式执行使用 `-n` 非 GUI 模式。
