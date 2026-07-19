# 路线规划自然语言评测

本评测用于验证完整一轮规划链路：

`constraint_extract -> planning_decision -> geo_resolve -> poi_retrieve -> route_generate -> route_validate -> route_evaluate -> route_present`

评测入口：

```powershell
D:\conda3\envs\GenTrip\python.exe scripts\evaluate_route_plans.py
```

如需保存详细结果：

```powershell
D:\conda3\envs\GenTrip\python.exe scripts\evaluate_route_plans.py --json-output .runtime_logs\route_eval.json
```

## 用例文件

自然语言用例位于：

`backend/fixtures/route_eval_cases.json`

默认评测使用进程内存运行时，并关闭 LLM，因而不依赖本机 Postgres、Redis 或 DeepSeek。只有需要验证持久化链路时才传入 `--persistent`；只有单独做模型 smoke test 时才传入 `--live-llm`。

当前覆盖：

| id | 自然语言输入 | 核心检查 |
| --- | --- | --- |
| xuhui_half_day_leisure_food | 徐汇区半天逛吃，人均120元 | 餐饮 + 游玩、预算、时长、合法路线 |
| xujiahui_nearby_coffee | 徐家汇附近喝咖啡，人均80元 | 商圈解析、咖啡类目、预算 |
| huangpu_exhibit_coffee_return_by | 黄浦区看展览再喝咖啡，18点前回 | 返回时间、展览/咖啡多域覆盖 |
| pudong_three_hour_sightseeing | 浦东新区3小时公园散步，人均80元 | 纯游玩路线、时间预算 |
| jingan_half_day_shopping | 静安区半天购物逛街，人均100元 | 购物域召回、购物路线生成 |

## 合法性判断

脚本会同时检查链路自身输出和独立规则。Plan 与 Replan 都以 `RouteJudge` 为唯一硬约束判断入口；不允许把“违规最少”的路线提升为可用路线：

- `run_status == completed`
- Top route 在 `validation_reports` 中为 `feasible=true`
- 非 `degraded` 路线
- 人均不超过 `budget_per_person`
- 总时长不超过 `time_budget_minutes`
- 最后一站离开时间不晚于 `return_by`
- 每站到达/离开顺序合法
- 交通时间非负，且不超过 `90` 分钟
- 营业窗口覆盖完整到店与停留区间
- 明确排除项不出现在名称或品类中
- 本地交通估算同时记录乐观、期望和保守时长；期望值用于硬校验，保守值用于风险提示

## 质量评分

总分 `0-1`，默认每个 case 通过 `min_quality_score` 控制门槛。

| 子项 | 权重 | 含义 |
| --- | ---: | --- |
| legal | 0.35 | 是否完成且合法 |
| coverage | 0.25 | 是否覆盖期望 domain / category |
| stop_count | 0.15 | 站点数是否达到用例要求 |
| budget | 0.10 | 是否符合预算 |
| time | 0.10 | 是否符合时长或返回时间 |
| relaxation | 0.05 | 是否无降级、少放宽 |

默认脚本会在任一 case 未通过时返回非零退出码；调试时可使用：

```powershell
.venv312\Scripts\python.exe scripts\evaluate_route_plans.py --no-fail
```
