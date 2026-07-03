# POI Demo Data Factory

本文档说明如何为 GenTrip 制造一批“美团风格”的可用 POI 数据。这里的“美团风格”指字段形态和用户决策信息密度相似：分类、商圈、评分、人均、销量热度、排队、营业时间、套餐、标签、UGC 摘要等；不表示数据来自美团，也不应伪装成真实平台抓取。

## 目标

路线规划需要的 POI 不是简单的 `{name, lat, lng}`。至少要支撑四类判断：

- 检索：用户说“徐汇 200 以内逛吃 3 小时”，系统能按区域、品类、价格、标签召回。
- 排序：能用评分、热度、距离、排队、场景匹配做综合打分。
- 规划：能用营业时间、推荐停留时长、坐标、预约要求做时间轴。
- 解释：每站要有 `ugc_summary` 和短评依据，避免 LLM 编造理由。

## 推荐字段

核心字段：

- `poi_id`
- `name`
- `category`
- `sub_category`
- `district`
- `business_area`
- `address`
- `location.lat`
- `location.lng`
- `avg_price`
- `rating`
- `review_count`
- `popularity`
- `queue_minutes`
- `opening_hours`
- `recommended_duration_min`
- `tags`
- `signature_items`
- `ugc_summary`
- `review_snippets`

美团式增强字段：

- `taste_score`
- `environment_score`
- `service_score`
- `monthly_sales`
- `deals`
- `reservation`
- `parking`
- `constraints.dietary`
- `constraints.scene_fit`
- `constraints.noise_level`

## 制造原则

1. 店名、评分、短评、销量、套餐一律合成，不从平台复制。
2. 坐标可以用真实商圈附近的 plausible anchor，方便路线优化测试。
3. 同一商圈要覆盖不同价位和停留时长，否则路线优化没有选择空间。
4. 每个 POI 至少给 1 条正向短评和 1 条 mixed 短评，方便解释权衡。
5. 不要让所有 POI 都高分，评分、排队、价格要有差异。
6. 景点/公共空间的 `avg_price` 可以是 0，`monthly_sales` 可以是 0。
7. 每条数据都要能回答：为什么选、什么时候去、适合谁、不适合谁。

## 推荐种子分布

P0 demo 可以先做 50-100 条：

- 徐汇：20 条，覆盖衡复、徐家汇、田林、武康路。
- 静安：15 条，覆盖静安寺、南京西路、愚园路。
- 黄浦：15 条，覆盖人民广场、外滩、豫园。
- 长宁/浦东：各 10 条，用于跨区路线和夜景路线。

品类比例：

- 美食 60%
- 咖啡/甜品 15%
- 景点/街区 10%
- 休闲娱乐 10%
- 购物/体验 5%

## 接入建议

起步阶段建议优先用 OpenStreetMap 生成真实 POI 名称和坐标：

```bash
python scripts/fetch_osm_pois.py --limit 200 --output data/poi_seed_osm_minimal.json
```

这个脚本输出 `poi_seed.v0.osm`，字段很少：`id`、`name`、`category`、`area`、`location`、`open_hours`、`tags`、`note`、`source`。这些字段足够支撑早期检索、筛选、地图展示和路线串联。

如果网络不可用或需要稳定 demo 数据，可以先用 `data/poi_seed_v0_minimal.json`。它字段少、名称更多，适合先把检索、筛选、路线串联跑通。

后续需要做排序解释、UGC 证据和降级链路时，再用 `data/poi_seed_meituan_style.json` 这种富字段版本。建议导入时拆成三类索引：

- POI 结构化库：基础字段、坐标、价格、营业时间、标签。
- UGC 库：`ugc_summary`、`review_snippets`，用于 grounded explanation。
- 向量字段：`name + category + business_area + tags + signature_items + ugc_summary`。

示例 embedding 文本：

```text
梧桐里小馆 本帮江浙菜 徐汇区 衡山路/复兴西路 朋友聚餐 长辈友好 可预约 口味稳定 葱油鸡 响油鳝丝 桂花酒酿圆子 菜品偏经典本帮口味，甜咸平衡，环境安静，适合不赶时间的正餐。
```

## 质量检查

导入前建议做这些检查：

- `poi_id` 唯一。
- 坐标在城市合理范围内。
- `avg_price >= 0`，`rating` 在 0-5。
- `opening_hours` 可解析。
- 每个 POI 至少有 `ugc_summary`。
- `recommended_duration_min` 与品类匹配。
- `queue_minutes.weekend >= queue_minutes.weekday`，除非有明确原因。
