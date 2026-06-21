# POI 检索节点设计

> 范围：**用户提问 → 候选 POI 列表**（`poi_retrieve` 节点及支撑模块）。  
> 不涉及：路线生成、校验、评估、展示。

---

## 1. 设计目标

- 从自然语言 query 检索相关 POI，写入 `GraphState.candidate_pois`
- **多意图域并行**：用户提到几个方向（吃 / 玩 / 买），就激活几个域分别检索，再合并
- **取消 MIXED 类型**：混合需求 = 多域组合，不是第 4 种 purpose
- **类目检索跟 POI 数据走**：以 `category_taxonomy.json` 叶子类目为索引 vocabulary
- **零 Clarify**：解析缺省写入 `assumptions`，检索侧按域独立放宽

---

## 2. 意图域（Intent Domain）

与 POI 数据 `purpose_map` 三族一一对应：

| 域 `domain` | 含义 | POI 叶子类目 |
|-------------|------|-------------|
| `dining` | 饮食 | 本帮菜、火锅、日料、咖啡… |
| `sightseeing` | 游玩 / 逛 | 观光、博物馆、文化、公园 |
| `shopping` | 购物 | 购物 |

一次 query 激活 **0~3 个域**，不是固定三维全开。

---

## 3. 节点边界

### 输入（GraphState）

| 字段 | 用途 |
|------|------|
| `user_query` | 主解析来源 |
| `constraints` | 可选；沿用上游 `constraint_extract` 的 district / budget / preferred_cuisines / activity_tags |

### 输出（GraphState）

| 字段 | 说明 |
|------|------|
| `candidate_pois` | 合并后的候选 POI（每条带 `dimension`） |
| `candidate_pois_by_dim` | 按域分组的 POI（debug / 下游组路线） |
| `retrieval_meta` | 检索计划与各域 relax 元数据 |
| `assumptions` | 检索阶段放宽说明（如忽略 budget） |
| `relaxed_constraints` | 如 `dining:R1` |

### 不负责

- 路线组合、时长/预算校验、Top-K 路线输出

---

## 4. 处理流程

```
user_query (+ constraints)
        │
        ▼
 parse_retrieval_plan()          services/poi_query_parser.py
        │
        ▼
 RetrievalPlan
   ├─ filters: { district, budget_per_person }
   └─ domains: [ DomainSpec, ... ]
        │
        ▼
 retrieve_by_plan()              services/poi_retrieval.py
   每个 DomainSpec 独立：
     resolve_domain_leaves → 索引召回 → 区域/预算过滤 → 域内 R0~R4 放宽
        │
        ▼
 merge + 按 rating 排序 → candidate_pois
```

---

## 5. 检索计划 `RetrievalPlan`

```python
RetrievalPlan:
  raw_query: str
  filters:
    district: str | null
    budget_per_person: int | null      # 主要约束 dining 域
  domains: list[DomainSpec]

DomainSpec:
  domain: dining | sightseeing | shopping
  categories: list[str] | null          # 叶子或 group（中餐/日料）
  poi_names: list[str]                  # 点名店，模糊匹配 name
```

### 域激活规则（摘要）

| 用户表述 | 激活域 |
|---------|--------|
| 日料 / 火锅 / 吃饭 | `dining` |
| 逛 / 玩 / 博物馆 / 公园 | `sightseeing` |
| 购物 / 买 | `shopping` |
| 逛吃 | `dining` + `sightseeing` |
| 附近好玩的（无其他） | 默认 `sightseeing` |

上游 `constraints.purpose=MIXED` 会映射为多域，**不再读取 `purpose_map.MIXED`**。

---

## 6. 类目映射

文件：`fixtures/category_taxonomy.json`

- `purpose_map.DINING / SIGHTSEEING / SHOPPING`：各域允许的叶子
- `parents` + `groups`：餐饮 group → 叶子展开（中餐 → 本帮菜/火锅…）
- `aliases`：日本料理 → 日料

单域叶子解析：`resolve_domain_leaves(domain, categories)`

- `categories` 有值 → `expand_categories(categories) ∩ domain_leaves`
- `categories` 为空 → 该域全部叶子

**不做** `preferred_cuisines ∩ purpose` 全局交集。

---

## 7. 分域放宽策略

每域候选 `< MIN_CANDIDATES(3)` 时，**仅在该域内** 升级：

### dining

| 步骤 | 变化 |
|------|------|
| R0 | 原始 district + budget + categories |
| R1 | 忽略 budget |
| R2 | categories 扩到父级 group |
| R3 | categories 清空（全部餐饮叶子） |
| R4 | district 清空（全市） |

### sightseeing

| 步骤 | 变化 |
|------|------|
| R0 | district + categories |
| R1 | categories 清空 |
| R2 | district 清空 |

### shopping

| 步骤 | 变化 |
|------|------|
| R0 | district |
| R1 | district 清空 |

---

## 8. 合并与排序

- 每域最多召回 `PER_DOMAIN_LIMIT=8` 条
- 合并去重后最多 `MERGED_LIMIT=20` 条
- 按 `star` 降序；`ScoredPoi.dimension` 标记来源域

---

## 9. 代码结构

```
backend/src/
├── models/retrieval.py           # RetrievalPlan / DomainSpec / IntentDomain
├── services/
│   ├── poi_query_parser.py       # query → RetrievalPlan
│   ├── poi_retrieval.py          # RetrievalPlan → candidate POIs
│   └── category_taxonomy.py      # 域 → 叶子、group 展开
├── graph/nodes/poi_retrieve.py   # LangGraph 节点入口
└── fixtures/category_taxonomy.json
```

---

## 10. 示例

**Query：** `徐汇逛吃，日料，人均 150`

**Plan：**

```json
{
  "filters": { "district": "徐汇区", "budget_per_person": 150 },
  "domains": [
    { "domain": "dining", "categories": ["日料"] },
    { "domain": "sightseeing", "categories": null }
  ]
}
```

**结果：**

- `candidate_pois_by_dim.dining`：徐汇区日料店（budget 不足时 dining 域 R1 放宽）
- `candidate_pois_by_dim.sightseeing`：徐汇区博物馆/公园等
- 合并写入 `candidate_pois`，各自带 `dimension`

---

## 11. 与旧模型差异

| 旧 | 新 |
|----|-----|
| `purpose=MIXED` + 全局叶子并集 | 多 `DomainSpec` 并行 |
| `preferred ∩ purpose` | 域内 `categories` 直接展开 |
| 全局 R0~R5 | 每域独立放宽 |
| 无 dimension 标签 | `ScoredPoi.dimension` |

`constraint_extract` 仍输出旧 `Constraints` 字段；`poi_query_parser` 负责映射为 `RetrievalPlan`。后续可将解析完全收进本节点。

---

## 12. 后续扩展

- POI 新增类目族（酒店、亲子）→ 增加 `IntentDomain` + `purpose_map` 条目
- 距离排序：在 `_sort_pois` 引入 `user_lat/lng`
- 点名 POI：加强 `poi_names` 与 ES 模糊匹配
- `route_generate` 消费 `candidate_pois_by_dim` 按域组站

---

## 13. 单节点隔离测试

完整 Plan 链路会经过 `route_generate` / `route_validate` 等节点，**无法单独验证 poi_retrieve 的 state**。
应使用 **节点级单元测试**：只调用 `poi_retrieve`，断言 merge 后的 state 字段。

### pytest（推荐）

```bash
cd backend
source .venv/bin/activate

# 只跑 poi_retrieve 节点测试
pytest tests/test_poi_retrieve_node.py -v

# 或用 marker 筛所有节点隔离测试
pytest -m node -v
```

测试辅助函数：`tests/test_poi_retrieve_node.py` 中的 `run_poi_retrieve_node()`  
返回 `{**initial_state, **node_update}`，与 LangGraph 单步 merge 一致。

重点断言字段：

- `candidate_pois` / `candidate_pois_by_dim`
- `retrieval_meta.plan` / `retrieval_meta.by_domain`
- `assumptions` / `relaxed_constraints`
- `current_phase == "poi_retrieve"`

### 本地调试脚本（打印 JSON）

```bash
python scripts/run_poi_retrieve_node.py "徐汇逛吃，日料"
python scripts/run_poi_retrieve_node.py "静安日料，人均120" --district 静安区 --budget 120
```

输出该节点后的 state 快照，不经过后续节点。

### 前两节点：constraint_extract → poi_retrieve

```bash
# 使用 .env 里的 LLM 配置
python scripts/run_extract_and_poi_nodes.py "静安日料，人均120"

# 强制规则模式
python scripts/run_extract_and_poi_nodes.py "徐汇逛吃" --mode rule_only

# pytest（Mock LLM，无需 Key）
pytest tests/test_nodes_extract_and_poi.py -v

# 真实 LLM（需 .env 配 Key 且非 rule_only）
pytest tests/test_nodes_extract_and_poi.py -v -m llm_live
```

Helper：`tests/node_runners.py` 中的 `run_extract_and_poi_nodes()`  
打印结构见 `snapshot_after_extract_and_poi()`（分 constraint_extract / poi_retrieve 两段）。
