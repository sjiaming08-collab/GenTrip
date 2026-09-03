# 路线生成阶段：完整推导与修复方案

## 一、当前 `route_generate` 的运作机制（摘要）

```
candidate_pois (扁平列表, 最多20条)
  │
  ▼
_group_pois()  ── 硬编码 category→domain 映射分桶, 每桶最多6条
  │
  ▼
_route_skeletons()  ── 硬编码 if-else 生成 domain 序列骨架（最多3个）
  │  例: dining+sightseeing → ["sightseeing","dining","sightseeing"], ["dining","sightseeing","dining"], ["sightseeing","dining"]
  │
  ▼
_generate_for_skeleton()  ── Beam Search (width=4), 逐 slot 填 POI
  │  评分: POI质量 - 交通惩罚 - 预算惩罚 - 相邻同类目惩罚(-0.2)
  │  交通: Haversine直线距离 ÷ 4km/h × 60, clamp[8,35]分钟
  │  停留: dining 75min, 咖啡/甜品 45min, 其他 60min
  │
  ▼
去重 Top-5 → _build_route() 从 DEFAULT_START_HOUR=14:00 排时间轴 → candidate_routes
```

### 当前机制的三大硬伤

| # | 问题 | 根因 |
|---|------|------|
| 1 | 出发时间恒为 14:00 | `DEFAULT_START_HOUR` 常量，未读 return_by/input_ts/场景 |
| 2 | 骨架纯规则枚举 | `_route_skeletons()` 硬编码域交替模式，无法理解"先日料再咖啡"这类同域子类目顺序 |
| 3 | 骨架与 POI 池无交互 | 规则不知道 POI 池里有什么，可能生成"shopping"骨架但池里没购物 POI |

---

## 二、出发时间推导链（替代 14:00）

### 完整推导

```
优先级从高到低：

P1: return_by 倒推
    输入: return_by="19:00", poi_count=3, domains=["dining","sightseeing"]
    预估总时长 = Σ 每站平均停留(60~75min) + Σ 站间交通(估15min/段)
              ≈ 3×65 + 2×15 = 225min
    return_by 分钟 = 19×60 = 1140
    最晚出发分钟 = 1140 - 225 = 915 = 15:15
    再减 30min 缓冲 → 14:45
    start_hour = 14.75 (即 14:45)

P2: 当前时刻 + 缓冲
    输入: input_ts="2026-06-28T11:22:00Z" (用户说"附近有什么好吃的")
    当前时刻 = 11:22
    缓冲 = 30min (用户出发准备)
    start_hour = 12:00 (向上取整到整点或半点附近)
    仅当用户位置可用且query含"附近/现在/当前"等词时触发

P3: 场景推断
    输入: domains, preferred_cuisines, user_query
    场景判定规则:
      - preferred_cuisines 含咖啡/甜品 + time≈下午 → 下午茶 → start=14:00
      - domain纯dining + time≈11:00~13:00 → 午餐 → start=11:30
      - domain纯dining + time≈17:00~19:00 → 晚餐 → start=18:00
      - sightseeing为主 + time<12:00 → 上午出游 → start=9:30
      - 其他 → start=10:00 (通用默认)

P4: 兜底
    start_hour = 10:00
```

### 推导函数签名

```python
def _derive_start_hour(
    constraints: dict,        # return_by, time_budget_minutes, poi_count, domains
    input_ts: str | None,     # 用户发消息的时刻
    user_query: str,          # 用于判断"附近/现在"语义
    user_lat: float | None,   # 有位置才触发 P2
    user_lng: float | None,
) -> float:
```

---

## 三、骨架生成：LLM 定结构 + Beam Search 填细节

### 3.1 为什么不是纯规则

硬编码 `_route_skeletons()` 的本质是**域级别的穷举**（dining/sightseeing/shopping 三种域的排列），它做不到：

- **显式顺序**：「先去武康路→再去日料→最后咖啡」→ skeleton 应该是 `[sightseeing, dining, dining]` 且后两个 slot 有 category 约束
- **同域子类目顺序**：「吃火锅→再去咖啡」→ 同是 dining 域，但火锅和咖啡是不同的 slot 类型
- **域内节奏**：「逛→吃→歇一歇再逛→再吃」→ 4 站路线，规则写死最多 3 种骨架

### 3.2 为什么不是纯 LLM

LLM 做不到的是：

- 从 6×6×6=216 种 POI 组合中找最高分的
- 精确计算交通时间（需要 POI 坐标和地图路径规划；高德不可用时才回退 Haversine 区间估算）
- 保证 POI 不重复、约束不超预算

### 3.3 混合架构

```
                    user_query
                        │
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
   constraints    candidate_pois   candidate_pois_by_dim
        │               │               │
        │               ▼               │
        │   ┌───────────────────┐       │
        │   │  POI 摘要生成     │       │
        │   │  (规则,非LLM)     │       │
        │   │                   │       │
        │   │  输出:            │       │
        │   │  dining: 日料×3   │       │
        │   │         本帮菜×2  │       │
        │   │         火锅×1    │       │
        │   │  sightseeing:     │       │
        │   │         博物馆×2  │       │
        │   │         公园×2    │       │
        │   └───────┬───────────┘       │
        │           │                   │
        │           ▼                   │
        │   ┌───────────────────────────┐
        │   │  LLM 骨架生成             │
        │   │  (DeepSeek, json_object)  │
        │   │                           │
        │   │  输入: query + 约束 +     │
        │   │        POI摘要            │
        │   │  输出: RouteSkeleton[]    │
        │   │  失败→回退规则骨架        │
        │   └───────┬───────────────────┘
        │           │
        │           ▼
        │   RouteSkeleton[]
        │   [{slots: [                           ← LLM 输出
        │     {domain:dining, categories:[日料]},
        │     {domain:sightseeing, categories:null},
        │     {domain:dining, categories:[咖啡]}
        │   ]}, ...]
        │           │
        │           ▼
        │   ┌───────────────────────────┐
        │   │  Beam Search 填 POI       │
        │   │  (现有逻辑, 增强)          │
        │   │                           │
        │   │  每 slot: 从对应域bucket  │
        │   │  按 categories 过滤       │
        │   │  枚举组合→评分→Top-4      │
        │   └───────┬───────────────────┘
        │           │
        │           ▼
        │   BeamCandidate[]
        │           │
        │           ▼
        └─────── _derive_start_hour()
                        │
                        ▼
                  _build_route()
                        │
                        ▼
                  candidate_routes
```

### 3.4 LLM 输出的数据结构

```python
class SlotHint(BaseModel):
    """LLM 对单个 slot 的约束"""
    domain: str                    # "dining" | "sightseeing" | "shopping"
    categories: list[str] | None   # ["日料"] 或 null(不限制)
    avoid_categories: list[str]    # ["火锅"] 用户说不要的
    note: str | None               # "主食", "甜品收尾" 等语义标记

class RouteSkeleton(BaseModel):
    """LLM 输出的一条骨架"""
    slots: list[SlotHint]
    rationale: str                 # "用户要求逛→吃→咖啡，甜品收尾"
```

### 3.5 LLM Prompt 设计

**System:**
```
你是 GenTrip 路线骨架规划器。根据用户需求、可用 POI 摘要、约束条件，
输出 1~3 条 domain 级别的路线骨架。

规则:
1. 仔细理解用户的顺序偏好：「先X再Y」「然后Z」要体现在 slot 顺序里
2. 同域内有子类目节奏时用 categories 约束（如 "日料正餐→咖啡收尾" 都是 dining 域
   但不同 slot）
3. 每个 slot 只能用一个 domain；categories 是可选的细化
4. 骨架数量根据用户需求复杂度：
   - 模糊（"逛吃"）→ 2~3 条不同风格
   - 明确（"日料→咖啡"）→ 1~2 条
5. avoid_categories 只在用户明确否定时填写
```

**User:**
```
用户: {user_query}
约束: {poi_count}站, 人均{ budget }元, 时长{time_budget_minutes}分钟
{return_by_line}

可用POI摘要:
{dining_summary}
{sightseeing_summary}  
{shopping_summary}

输出JSON:
{
  "skeletons": [
    {
      "slots": [
        {"domain":"dining","categories":["日料"],"avoid_categories":[],"note":"正餐"},
        {"domain":"sightseeing","categories":null,"avoid_categories":[],"note":null},
        {"domain":"dining","categories":["咖啡"],"avoid_categories":[],"note":"收尾"}
      ],
      "rationale": "..."
    }
  ]
}
```

### 3.6 降级策略

```
LLM 调用
  ├─ 成功 + schema 校验通过 → 使用 LLM 骨架
  ├─ 超时 / HTTP 错误 → 回退 _rule_skeletons()
  ├─ JSON 解析失败 → 回退 _rule_skeletons()
  └─ LLM 未配置 (rule_only 模式) → 直接 _rule_skeletons()
```

`_rule_skeletons()` 保留现有硬编码逻辑作为兜底，确保**始终出路线**。

---

## 四、完整数据流（route_generate 新流程）

```
async def route_generate(state: GraphState) -> dict:
    # ── 0. 读取输入 ──
    constraints = state["constraints"]
    pois_raw = state["candidate_pois"]
    pois_by_dim = state.get("candidate_pois_by_dim") or {}
    geo_scope = state.get("geo_scope") or {}

    # ── 1. 构建 POI 桶（优先 candidate_pois_by_dim）──
    if pois_by_dim:
        buckets = _buckets_from_by_dim(pois_by_dim)  # 新函数
    else:
        buckets = _group_pois(pois_raw)               # 现有回退

    # ── 2. 生成 POI 摘要（供 LLM prompt）──
    summary = _summarize_buckets(buckets)            # 新函数

    # ── 3. 骨架生成（LLM 优先 → 规则兜底）──
    skeletons = await _generate_skeletons(
        constraints, summary, state["user_query"]
    )

    # ── 4. Beam Search 填 POI（复用现有逻辑）──
    candidates = []
    for sk in skeletons:
        beams, _ = _generate_beams_for_skeleton(
            sk, buckets=buckets, constraints=constraints
        )
        candidates.extend(beams)

    # ── 5. 推导出发时间 ──
    start_hour = _derive_start_hour(
        constraints,
        input_ts=state.get("input_ts"),
        user_query=state["user_query"],
        user_lat=state.get("user_lat"),
        user_lng=state.get("user_lng"),
    )

    # ── 6. 构建 RoutePlan ──
    routes = []
    for beam in unique_top_k(candidates):
        routes.append(_build_route(
            name=..., summary=...,
            pois=beam.pois,
            start_hour=start_hour,
        ))

    return phase_update("route_generate", candidate_routes=[...])
```

---

## 五、与现有代码的改动面

### 修改文件

| 文件 | 改动 |
|------|------|
| `models/route.py` | `RouteStop` 加 5 个可选字段：`rating, price_per_person, lat, lng, business_hours` |
| `graph/state.py` | 加 `relax_round: int` 到 L2 |
| `graph/nodes/route_generate.py` | ① `_derive_start_hour()` 新函数 ② `_buckets_from_by_dim()` 新函数 ③ `_summarize_buckets()` 新函数 ④ `_generate_skeletons()` 替换 `_route_skeletons()` ⑤ `_build_route()` 填充新字段 + 使用动态 start_hour ⑥ `_domain_of_poi()` 改为优先读 `poi.dimension` |
| `graph/nodes/route_validate.py` | 加 `return_by` 校验 + 营业时间校验 + `auto_relax` 改为写 `relax_round` |
| `graph/nodes/route_evaluate.py` | 使用 `stop.rating` 而非硬编码 4.5 |
| `graph/nodes/route_present.py` | 区分 `reply_type` + 完整输出 assumptions |
| `graph/plan_graph.py` | `route_validate` 后加条件边 |
| `llm/schemas.py` | 新增 `RouteSkeletonResult` schema |
| `llm/prompts/` | 新增 `route_skeleton.py` prompt 模板 |
| `llm/` | 新增 `route_skeleton_llm.py` LLM 调用 |

### 新增文件

| 文件 | 内容 |
|------|------|
| `llm/prompts/route_skeleton.py` | LLM 骨架生成 prompt |
| `llm/route_skeleton_llm.py` | LLM 调用 + schema 校验 + 降级 |

---

## 六、验证

```bash
# 单元测试
pytest tests/test_route_generate.py -v          # 更新：验证 start_hour 推导、RouteStop 新字段
pytest tests/test_route_evaluate.py -v          # 新增：验证 rating 来自真实数据
pytest tests/test_route_validate.py -v          # 新增：return_by/营业时间/auto_relax 循环

# 端到端
pytest tests/test_plan_cold_path.py -v          # 确认仍返回 completed

# 手动脚本
python scripts/run_plan.py "7点前回家，徐汇逛吃"        # return_by 生效
python scripts/run_plan.py "先去武康路再去日料最后咖啡"   # LLM 骨架生效
python scripts/run_plan.py "静安日料人均500"             # auto_relax 放宽后仍出路线
```
