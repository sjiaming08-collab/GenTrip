# POI 数据设计

> 数据源：[美团点评 POI 数据开放接口说明](https://poiopen.dianping.com/instructions/doc/poi.html)  
> 关联文档：[`graph-state-design.md`](graph-state-design.md) · [`agent-runtime-design.md`](agent-runtime-design.md)

---

## 1. 设计目标

GenTrip 的 POI 数据只服务 **路线规划流水线**，不是点评详情页复刻。

| 节点 | 对 POI 的需求 |
|------|--------------|
| `poi_retrieve` | 按城市/区域/类目/预算召回 Top-N |
| `route_generate` | 组合多站、估算停留与顺路 |
| `route_validate` | 预算、时长、营业窗口可行性 |
| `route_evaluate` | 质量/偏好/执行度打分 |
| `route_present` | 展示名称、类目、人均、头图（可选） |

**原则：**

- 开放接口字段很多，**只落库与流水线真正用到的子集**
- 原始响应完整保留在 `raw_payload`，业务模型只暴露稳定字段
- 同步 API 读本地库/缓存；点评开放接口走 **离线同步 + 按需补全**

---

## 2. 点评开放接口：我们用什么

### 2.1 使用的 API（3 个）

| 接口 | 路径 | 用途 |
|------|------|------|
| 开放城市 | `POST /router/city/opencity` | 校验同步范围（如「上海」） |
| 分页扫描 | `POST /router/poi/pagequerypoi` | 按 `cityname` + `page` **离线灌库** |
| 批量详情 | `POST /router/poi/batchgetpoi` | 按 `openshopid`（≤100）补全 star/avgprice/营业时间等 |

> `getsinglepoi` 与 `batchgetpoi` 能力重叠；批量场景统一用 `batchgetpoi`。

### 2.2 暂不使用的 API / 字段域

| 类别 | 原因 |
|------|------|
| `ugcs` 评论正文 | 体积大、同步贵；路线规划用聚合信号（star/reviewCount）即可 |
| `shopPics` / `dishs` 全量 | 属展示增强，MVP 仅保留 `headPic` |
| 各类 `*Url`（除详情页 1 条） | 与排程无关 |
| `takeawayinfo` / `dealInfo` / `mallInfo` | 非出行串联核心 |
| `shopI18ns` | 当前产品仅中文 |

---

## 3. 字段精选（点评 → GenTrip）

从 [POI 开放字段说明](https://poiopen.dianping.com/instructions/doc/poi.html) 中选取 **三档**：

### 3.1 Tier-1 必存（检索 + 排程 + 校验）

| 点评字段 | 类型 | GenTrip 字段 | 用途 |
|----------|------|--------------|------|
| `openshopid` | string | `poi_id` | 全局唯一主键（前缀 `dp:`） |
| `openstatus` | int | `status` | `1=在线` 才参与召回 |
| `name` | string | `name` | 展示、RouteStop |
| `branch_name` | string | `branch_name` | 与 name 合并展示 |
| `city` | string | `city` | 同步维度、城市过滤 |
| `address` | string | `address` | 展示、地理编码辅助 |
| `latitude` | double | `lat` | 距离、顺路、地图 |
| `longitude` | double | `lng` | 同上 |
| `categories` | list | `categories` | 叶子类目；映射 `category` 主标签 |
| `star` | float | `rating` | 质量分、`route_evaluate` |
| `avgprice` | int | `price_per_person` | 预算校验 |
| `business_hour` | string | `business_hours` | 营业窗口（`route_validate` 二期） |

### 3.2 Tier-2 增强（排序与体验，同步时一并拉）

| 点评字段 | 类型 | GenTrip 字段 | 用途 |
|----------|------|--------------|------|
| `highquality` | int | `is_high_quality` | 检索加权 |
| `isBlackPearl` | int | `is_black_pearl` | 高质量路线偏好 |
| `reviewCount` | int | `review_count` | 热度信号 |
| `bookable` | string | `bookable` | 可预订性（执行度） |
| `queueable` | boolean | `queueable` | 排队风险（执行度） |
| `headPic` | string | `head_pic` | `presentation` 卡片 |
| `brandName` | string | `brand_name` | 去重、连锁识别 |
| `reviewTags` | list | `review_tags` | 偏好匹配（如「适合聚会」） |

`reviewTags` 只存 `{tag, hit}`，不存评论内容。

### 3.3 Tier-3 不落库（明确排除）

`telephone`、`special`、`picCount`、`dishs.*`、`ugcs.*`、全部跳转 URL 字段、`takeaway*`、`mallInfo.*`、`dealInfo.*` 等。

---

## 4. GenTrip 内部模型（三层）

```
点评 API JSON
    ↓ 映射 + 清洗
PoiRecord（PostgreSQL / 本地索引）
    ↓ poi_retrieve 召回 + 打分
ScoredPoi（GraphState L3 candidate_pois）
    ↓ route_generate 选中
RouteStop（路线快照，仅保留展示所需字段）
```

### 4.1 `PoiRecord` — 本地主数据

```python
PoiRecord:
  poi_id: str                    # "dp:{openshopid}"
  source: "dianping"             # 固定
  openshopid: str                # 点评原始 ID
  status: "online" | "offline"   # openstatus 0/1
  name: str
  branch_name: str | null
  display_name: str              # name + branch_name 合并
  city: str                      # 如「上海」
  district: str | null           # 见 §5，非点评原生字段
  address: str
  lat: float
  lng: float
  categories: list[str]          # 叶子类目列表
  category: str                 # 主类目（categories[0] 或映射表）
  rating: float | null          # star
  price_per_person: int | null  # avgprice，缺失时为 0
  business_hours: str | null
  is_high_quality: bool
  is_black_pearl: bool
  review_count: int
  bookable: bool
  queueable: bool
  head_pic: str | null
  brand_name: str | null
  review_tags: list[{tag, hit}]
  synced_at: datetime           # 最后同步时间
  raw_payload: json | null      # 可选，调试/回溯
```

### 4.2 `ScoredPoi` — 流水线召回结果（对齐现有代码）

在 [`backend/src/models/route.py`](../backend/src/models/route.py) 基础上 **扩展可选字段**，保持向后兼容：

```python
ScoredPoi:
  # 现有（必填）
  poi_id: str
  name: str
  category: str
  district: str
  lat: float
  lng: float
  rating: float
  price_per_person: int
  composite_score: float = 0.0

  # 新增（可选，present 阶段使用）
  address: str | null = null
  business_hours: str | null = null
  head_pic: str | null = null
  review_count: int | null = null
  is_black_pearl: bool = false
  queueable: bool | null = null
```

`composite_score` 由 **检索层** 计算，不是点评 API 字段。

### 4.3 `RouteStop` — 路线快照（不变）

生成路线时把 `poi_id / poi_name / category` 写入 stop，避免后续 POI 变更影响已输出路线。不强制嵌入 `head_pic`（需要时按 `poi_id` 回查）。

---

## 5. `district` 与 `city` 的处理

点评分页接口只有 **`city`**（如「上海」），没有「徐汇区」。

GenTrip 的 `Constraints.district` 来自用户 query，召回策略：

```
1. city = opencity 白名单内城市（与 Constraints 或定位一致）
2. district = 用户约束中的区县（若有）
3. 召回：city 全量索引 + district 过滤
   - district 来源：逆地理编码（lat/lng → 区县）或 address 规则解析
   - MVP 可继续用 Mock fixtures 的 district；接点评后增加 geocode  enrichment 任务
4. district 为空时：按用户 lat/lng 半径检索，不强制区县匹配
```

---

## 6. 类目与 Constraints 的映射

| Constraints 字段 | 过滤方式 |
|------------------|----------|
| `purpose=DINING` | `categories` 命中美食叶子类目 |
| `purpose=SHOPPING` | 购物/商场类 |
| `purpose=SIGHTSEEING` | 景点/文化/观光类 |
| `preferred_cuisines` | 类目或 `review_tags.tag` 模糊匹配 |
| `activity_tags` | `review_tags` + 类目并集 |
| `budget_per_person` | `avgprice <= budget * 1.2`（检索放宽，validate 收紧） |

维护一张 **`category_mapping.yml`**（点评叶子类目 → GenTrip 标准类目），避免在节点里硬编码字符串。

---

## 7. 同步与更新策略

### 7.1 离线全量/增量（Worker）

```
opencity → 确认城市列表
  ↓
pagequerypoi(cityname, page=1..N)   # 每页 ~100
  ↓
写入 PoiRecord 基础字段（Tier-1 列表页已有字段）
  ↓
batchgetpoi(openshopid × 100)       # 补 Tier-2 + star/avgprice/business_hour
  ↓
geocode enrichment → district
  ↓
PostgreSQL upsert + 可选向量索引（constraint_embedding 近邻 POI）
```

### 7.2 在线读取（`poi_retrieve` 节点）

```
读本地 PoiRecord（禁止 Plan Run 内直调点评 API）
  → 过滤：status=online, city, district/半径, categories, budget
  → 排序：composite_score = f(rating, review_count, distance, preference_match, quality_flags)
  → Top-N → ScoredPoi → GraphState.candidate_pois
```

### 7.3  freshness

| 场景 | 策略 |
|------|------|
| 日常 | T+1 增量 page 扫描 |
| 详情字段缺失 | 按需 `batchgetpoi` |
| 用户反馈「店已关」 | 标记 offline，不参与召回 |

---

## 8. 字段映射速查表

| 点评 `openshopid` | `poi_id = f"dp:{openshopid}"` |
| 点评 `openstatus==1` | `status=online` |
| 点评 `name` + `branch_name` | `display_name` |
| 点评 `categories[0]` | `category`（经映射表） |
| 点评 `star` | `rating`（null → 4.0 默认，写 assumption） |
| 点评 `avgprice` | `price_per_person`（null → 0，表示免费/未知） |
| 点评 `latitude/longitude` | `lat/lng` |
| — | `district` 由 enrichment 写入 |
| — | `composite_score` 由检索层计算 |

---

## 9. 与 GraphState 的关系

| GraphState 字段 | POI 相关内容 |
|-----------------|-------------|
| L2 `constraints` | 驱动召回过滤条件 |
| L3 `candidate_pois` | `list[ScoredPoi]`，由 `poi_retrieve` 写入 |
| L3 `candidate_routes.stops` | 引用 `poi_id`，快照 `poi_name/category` |
| L4 `presentation` | 可选用 `head_pic`、人均、类目 |

---

## 10. 实现阶段

| 阶段 | 内容 | 状态 |
|------|------|------|
| **Step A** | `fixtures/pois.json` + `mocks/poi_store.py` | ✅ 当前 |
| **Step B** | `PoiRecord` PostgreSQL + 灌库脚本 + `services/poi_service.py` | ⬜ |
| **Step C** | 点评 `pagequerypoi` / `batchgetpoi` 同步 Worker | ⬜ |
| **Step D** | district geocode、`business_hour` 参与 `route_validate` | ⬜ |

### 10.1 Mock → 生产迁移

1. `fixtures/pois.json` 字段对齐 `PoiRecord`（增加 `openshopid`、`city`、`status`）
2. `poi_store.retrieve_pois` 改为调用 `PoiRepository.search(...)`
3. `ScoredPoi` 增加可选字段，测试与 API 响应保持兼容

---

## 11. 示例

### 11.1 点评 API 片段（分页列表）

```json
{
  "openshopid": "abc123",
  "name": "老吉士酒家",
  "branch_name": "天平路店",
  "city": "上海",
  "address": "徐汇区天平路xxx号",
  "latitude": 31.2104,
  "longitude": 121.4365,
  "categories": ["本帮菜"],
  "openstatus": 1
}
```

### 11.2 映射后的 `PoiRecord`

```json
{
  "poi_id": "dp:abc123",
  "source": "dianping",
  "openshopid": "abc123",
  "status": "online",
  "display_name": "老吉士酒家（天平路店）",
  "city": "上海",
  "district": "徐汇区",
  "category": "本帮菜",
  "rating": 4.6,
  "price_per_person": 120,
  "lat": 31.2104,
  "lng": 121.4365
}
```

### 11.3 写入 GraphState 的 `ScoredPoi`

```json
{
  "poi_id": "dp:abc123",
  "name": "老吉士酒家（天平路店）",
  "category": "本帮菜",
  "district": "徐汇区",
  "lat": 31.2104,
  "lng": 121.4365,
  "rating": 4.6,
  "price_per_person": 120,
  "composite_score": 0.92
}
```

---

## 12. 设计检查清单

- [ ] 召回只使用 `openstatus=1` 的 POI
- [ ] Plan Run 热路径不调用点评 HTTP API
- [ ] `poi_id` 稳定可回溯到 `openshopid`
- [ ] 缺失 `avgprice` / `star` 有 assumption 或默认值，不 Clarify
- [ ] 路线输出用 `RouteStop` 快照，不依赖 POI 实时变更
- [ ] 点评鉴权参数（appkey/session/sign）仅出现在 Worker 配置，不进 GraphState

---

## 13. 相关链接

- [美团点评 POI 数据开放接口说明](https://poiopen.dianping.com/instructions/doc/poi.html)
- 项目 GraphState：[`graph-state-design.md`](graph-state-design.md) §6.4 L3 `candidate_pois`
