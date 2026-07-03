# 相较上次 push 的修改总结

生成时间：2026-07-03  
对比基线：`origin/master` / `HEAD` 当前提交 `03d50d7 feat: 多域 POI 检索与 constraints.domains 模型`

## 总体概览

本次工作把 GenTrip 从“多域 POI 检索 + 基础冷路径”推进到一个更完整的本地规划闭环：

- 后端新增 `GeoResolver -> GeoScope -> POI retrieval` 的地理解析与检索边界。
- 冷路径图接入 `geo_resolve` 节点，使自然语言地点先被解析成结构化地理范围，再进入 POI 检索。
- POI 检索从单纯 district/category 过滤扩展为商圈、中心点半径、district、citywide 的地理放宽链路。
- 路线生成从固定 mock/简单拼接升级为规则化 slot skeleton + beam search + 时间/预算剪枝。
- 路线验证从只检查预算/时长升级为预算、总时长、返回时间、站点时间线、交通时间合法性校验，并支持 best-effort 降级但保留违规报告。
- 增加自然语言路线评测用例和自动化评测脚本，能判断一轮跑完后的路线是否合法、质量如何。
- 前端补齐 API、状态管理、表单提交和路线展示，使点击“开始规划”可以真实调用后端并展示结果。

## 后端链路改动

### 1. GeoResolver 与 GeoScope

新增文件：

- `backend/src/services/geo_resolver.py`
- `backend/src/graph/nodes/geo_resolve.py`
- `backend/fixtures/geo_gazetteer.json`
- `backend/tests/test_geo_resolver.py`
- `backend/tests/test_geo_scope_integration.py`

核心能力：

- 从自然语言 query 中识别地点 mention，例如 `徐家汇`、`黄浦区`、`武康路` 等。
- 通过本地 gazetteer 离线解析 district、business_area、中心点、半径、置信度。
- 支持 `user_lat/user_lng` 下的 nearby/reverse-geocode fallback。
- 暴露 provider 边界，预留 `AmapGeoProvider`，后续可以接高德等真实地理服务。
- 在图节点中输出 `geo_scope`，并把默认地理假设写入 `assumptions`。

### 2. PlanGraph 接入 geo_resolve

修改文件：

- `backend/src/graph/plan_graph.py`
- `backend/src/graph/state.py`

链路从原来的：

```text
constraint_extract -> poi_retrieve -> route_generate -> route_validate -> route_evaluate -> route_present
```

变为：

```text
constraint_extract -> geo_resolve -> poi_retrieve -> route_generate -> route_validate -> route_evaluate -> route_present
```

`GraphState` 新增：

- `geo_scope`
- `route_generation_meta`

其中 `route_generation_meta` 用于记录路线生成阶段的 skeleton、bucket 数量、开始时间、剪枝数量和 fallback 情况。

### 3. POI 检索增强

修改文件：

- `backend/src/models/retrieval.py`
- `backend/src/services/poi_query_parser.py`
- `backend/src/services/poi_retrieval.py`
- `backend/tests/test_poi_retrieval.py`

主要变化：

- `RetrievalFilters` 增加 `business_area`、`center_lat`、`center_lng`、`radius_m`、`geo_scope` 等字段。
- `parse_retrieval_plan` 优先读取 `state.geo_scope`，把地理解析结果转成检索过滤条件。
- `poi_retrieval` 新增地理放宽链路：
  - `business_area`
  - 中心点 + 半径
  - district
  - citywide
- POI 排序在有中心点时优先按距离，再按评分。
- 检索放宽会保留 assumption，例如“商圈候选不足，已扩大到周边半径检索”。
- 继续保留领域放宽 R0-R3，例如餐饮预算放宽、类目扩展、全餐饮类目。

### 4. 路线生成闭环

修改文件：

- `backend/src/graph/nodes/route_generate.py`
- `backend/tests/test_route_generate.py`

主要变化：

- 新增 `SlotHint`，用规则化 slot 表达路线 skeleton：domain、偏好 category、避免 category、note。
- 支持从自然语言中提取品类顺序，例如 `日料再咖啡` 会生成日料 slot 后接咖啡 slot。
- 使用 beam search 控制组合规模，避免 POI 自由组合导致分支爆炸。
- 生成阶段加入粗剪枝：
  - `time_budget_minutes * 1.2`
  - `budget_per_person * 1.2`
- 动态推导开始时间：
  - `return_by` 倒推
  - `附近/现在/马上` 结合用户当前位置和输入时间
  - 午餐/晚餐/咖啡/纯游玩场景默认时间
- 输出 `route_generation_meta`，包括：
  - `candidate_count`
  - `bucket_counts`
  - `skeletons`
  - `start_time`
  - `pruned_by_time`
  - `pruned_by_budget`
  - `used_fallback`

### 5. 路线验证闭环

修改文件：

- `backend/src/graph/nodes/route_validate.py`
- `backend/tests/test_route_validate.py`

主要变化：

- 验证预算是否超出 `budget_per_person`。
- 验证总时长是否超出 `time_budget_minutes`。
- 验证最后一站离开时间是否晚于 `return_by`。
- 验证每站 arrival/departure 时间顺序。
- 验证交通时间非负且不超过 `90` 分钟。
- 验证站点时间线是否满足上一站 departure + travel <= 下一站 arrival。
- 当没有完全合法路线时，选择违规最少的路线作为 best-effort 输出，但不把 `validation_report.feasible` 强行改成 true。
- 降级标记为 `route_validate_degraded_best_effort`，下游 presentation 会保留 degraded source。

## 数据、脚本与评测

新增文件：

- `data/poi_seed_meituan_style.json`
- `data/poi_seed_v0_minimal.json`
- `scripts/fetch_osm_pois.py`
- `scripts/evaluate_route_plans.py`
- `backend/fixtures/route_eval_cases.json`
- `docs/poi-data-factory.md`
- `docs/route-generate.md`
- `docs/route-evaluation.md`

主要变化：

- 增加最小 POI seed 和美团风格 POI seed，支持从轻量 schema 逐步扩展到更真实的数据格式。
- 增加 OSM/Overpass 拉取脚本，支持把外部 POI 转成本地 fixture。
- 增加自然语言评测集，覆盖：
  - 徐汇半天逛吃
  - 徐家汇附近喝咖啡
  - 黄浦看展览再喝咖啡，18 点前回
  - 浦东 3 小时游玩
  - 静安购物逛街
- `scripts/evaluate_route_plans.py` 会真实调用 `PlanService.run_plan()` 跑完整链路，并输出：
  - 是否 completed
  - Top route 是否合法
  - 预算/时长/返回时间/交通时间是否合法
  - domain/category 覆盖情况
  - stop 数量
  - quality score
  - issues

## 前端联调改动

修改/新增文件：

- `frontend/src/api/index.ts`
- `frontend/src/types/index.ts`
- `frontend/src/composables/useRoutePlan.ts`
- `frontend/src/composables/useSSEStream.ts`
- `frontend/src/App.vue`
- `frontend/src/components/RoutePlanner.vue`
- `frontend/src/components/ItineraryTimeline.vue`
- `frontend/src/components/PoiCard.vue`
- `frontend/src/components/MapView.vue`
- `frontend/src/components/FeedbackPanel.vue`
- `frontend/package.json`
- `frontend/tsconfig.json`
- `frontend/vite.config.mjs`

主要变化：

- `planRoute()` 从 `throw new Error('Not implemented')` 改为真实调用 `POST /api/v1/routes/plan`。
- 前端 TypeScript DTO 改成匹配当前后端 `PlanResponse`：`run_id`、`route_results`、`presentation`、`assumptions` 等。
- `RoutePlanner` 的“开始规划”按钮现在会 emit 真实 query。
- `useRoutePlan` 增加 `loading`、`error`、`currentRoute`、`selectedResult`、`history` 状态。
- `App.vue` 完成页面串联：输入、调用后端、展示 presentation、assumptions、备选路线、时间线、路线概览、反馈面板。
- `ItineraryTimeline` / `PoiCard` 能展示后端返回的 stop 信息。
- `MapView` 当前先展示站点顺序概览，因为后端 `RouteStop` 还没有下发经纬度；后续接地图 Marker 时需要扩展后端输出。
- `FeedbackPanel` 改成本地可提交，不再阻断主流程。
- 新增 `tsconfig.json`，让 `vue-tsc` 能真正执行类型检查。
- 新增 `vite.config.mjs`，并在 `package.json` 中让 dev/build/preview 使用该配置，避免当前 Windows sandbox 下 Vite 读取 TS config 的权限问题。

## 文档更新

修改/新增文档：

- `docs/agent-runtime-design.md`
- `docs/graph-state-design.md`
- `docs/poi-data-design.md`
- `docs/poi-retrieval-design.md`
- `docs/poi-data-factory.md`
- `docs/route-generate.md`
- `docs/route-evaluation.md`

文档方向：

- 明确 GeoScope/GeoResolver 的职责边界。
- 补充 GraphState 中 geo 与 route generation meta 的演进。
- 补充 POI 数据制造、OSM 获取、POI 检索放宽策略。
- 补充路线生成、过滤、验证的闭环设计。
- 补充自然语言路线评测的运行方式和质量评分标准。

## 验证情况

已通过：

```powershell
.venv312\Scripts\python.exe -m pytest backend\tests\test_geo_resolver.py backend\tests\test_geo_scope_integration.py backend\tests\test_poi_retrieval.py backend\tests\test_route_generate.py backend\tests\test_route_validate.py backend\tests\test_plan_cold_path.py
```

结果：`25 passed`

```powershell
.venv312\Scripts\python.exe scripts\evaluate_route_plans.py --no-fail
```

结果：`5/5 passed`

```powershell
cd frontend
node_modules\.bin\vue-tsc.cmd --noEmit
```

结果：通过，无输出错误。

```powershell
cd frontend
npm.cmd run build
```

结果：通过，Vite 成功构建。注意该命令在当前 Windows sandbox 内会被配置文件读取权限阻断，需要在非 sandbox/正常终端中运行。

全量 backend 测试当前仍有历史阻断：

```powershell
.venv312\Scripts\python.exe -m pytest backend\tests
```

结果：collection 阶段 3 个错误，原因是旧测试仍导入已经不存在的 `TripPurpose`：

- `backend/tests/test_constraint_rules.py`
- `backend/tests/test_constraint_service.py`
- `backend/tests/test_taxonomy_samples.py`

这与本次 GeoScope、POI 检索、路线生成/验证、前端联调的目标测试无关，但提交前建议单独清理这些旧测试或兼容模型。

## 不建议纳入提交的运行产物

当前工作区里有一些运行或安装产生的文件，不属于功能变更，建议提交前清理或加入忽略：

- `.venv312/`
- `.runtime_logs/`
- `%SystemDrive%/`
- `backend/src/**/__pycache__/`
- `backend/gentrip.egg-info/*`
- `frontend/node_modules/.vite/deps/*`
- `frontend/node_modules/.vue-global-types/`

其中 `frontend/dist/` 是构建产物，本次总结生成前已清理。

## 建议提交拆分

如果后续准备 commit，建议拆成 4-5 个提交：

1. `feat: add georesolver and geoscope integration`
2. `feat: enhance poi retrieval with geoscope relaxation`
3. `feat: implement deterministic route generation and validation loop`
4. `test: add route planning evaluation cases and scripts`
5. `feat(frontend): wire route planning api and result display`

这样可以避免把后端规划链路、数据制造、自动评测和前端联调混在一个过大的提交里。