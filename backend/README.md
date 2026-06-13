# GenTrip Backend

## 当前进度：Step A — 冷路径六段 + 最小 GraphState

```
constraint_extract → poi_retrieve → route_generate
  → route_validate → route_evaluate → route_present
```

## 目录结构

```
backend/
├── fixtures/           # Mock 数据
├── tests/
└── src/
    ├── api/            # HTTP 路由与 DTO
    ├── graph/          # LangGraph State + 节点 + 图组装
    │   └── nodes/      # 冷路径六段节点
    ├── models/         # Pydantic 领域模型
    ├── mocks/          # Mock POI 等（Step A）
    ├── services/       # 业务编排
    ├── config.py
    └── main.py
```

## 本地运行

```bash
cd backend
pip install -e ".[dev]"
pytest -v
uvicorn src.main:app --reload --port 8000
curl http://localhost:8000/api/v1/health
curl -X POST http://localhost:8000/api/v1/routes/plan \
  -H "Content-Type: application/json" \
  -d '{"query":"徐汇逛吃"}'
```

## 下一步（未实现）

- Step B：`route_bundle_search` 热路径
- LLM constraint_extract
- PostgreSQL POI
