"""FastAPI 应用入口 — API 路由注册 + LangGraph Agent 生命周期管理"""

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .graph.router import create_route_planner
from .models.route import RoutePlanResult, RouteFeedback


# ============================================================
# Request / Response DTOs
# ============================================================

class RoutePlanRequest(BaseModel):
    query: str = Field(description="用户自然语言输入")
    user_id: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None


class RoutePlanResponse(BaseModel):
    route_id: str
    source: str               # CACHE_HIT | CACHE_ADAPTED | FRESH_GENERATED
    plan_name: str
    stops: list[dict]
    metadata: dict
    map_deep_link: Optional[str] = None


class FeedbackRequest(BaseModel):
    route_id: str
    overall_score: float = Field(ge=1.0, le=5.0)
    poi_ratings: Optional[dict[str, float]] = None
    comments: Optional[str] = None


# ============================================================
# LangGraph Agent (模块级单例)
# ============================================================

_route_agent = None


def get_route_agent():
    """懒加载编译后的 LangGraph Agent"""
    global _route_agent
    if _route_agent is None:
        _route_agent = create_route_planner()
    return _route_agent


# ============================================================
# FastAPI 应用
# ============================================================

app = FastAPI(
    title="DeoReview API",
    description="本地智能路线规划系统",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vue 3 dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# API 端点 (抽象接口层 — 不实现具体逻辑)
# ============================================================

@app.post("/api/v1/routes/plan")
async def plan_route(request: RoutePlanRequest):
    """核心端点: NL 输入 → 路线方案 (两分支调度 + SSE)"""
    # TODO: 实现
    # agent = get_route_agent()
    # initial_state = {
    #     "user_query": request.query,
    #     "user_id": request.user_id,
    #     "user_lat": request.lat,
    #     "user_lng": request.lng,
    #     "candidate_templates": [],
    #     "match_score": 0.0,
    #     "branch": "generate",
    #     "feedback_processed": True,
    # }
    # result = await agent.ainvoke(initial_state)
    # return _to_response(result["route_result"])
    raise NotImplementedError


@app.get("/api/v1/routes/stream/{session_id}")
async def stream_route(session_id: str):
    """SSE 端点: 流式推送路线生成进度"""
    # TODO: 实现
    # async def event_generator():
    #     for phase in ["intent_parse", "search_cache",
    #                   "match_score", "branch", "render_output"]:
    #         yield f"event: progress\ndata: {phase}\n\n"
    #     yield f"event: complete\ndata: {final_json}\n\n"
    # return StreamingResponse(event_generator(), media_type="text/event-stream")
    raise NotImplementedError


@app.get("/api/v1/routes/{route_id}")
async def get_route(route_id: str):
    """查询历史路线"""
    # TODO: 实现
    raise NotImplementedError


@app.post("/api/v1/routes/{route_id}/feedback")
async def submit_feedback(route_id: str, feedback: FeedbackRequest):
    """提交反馈 → 异步更新知识库"""
    # TODO: 实现
    # agent = get_route_agent()
    # await agent.ainvoke({"feedback": RouteFeedback(...)})
    raise NotImplementedError


@app.get("/api/v1/poi/search")
async def search_poi(
    q: str = "",
    district: Optional[str] = None,
    category: Optional[str] = None,
    max_price: Optional[int] = None,
    limit: int = 20,
):
    """直接搜索 POI (不生成路线)"""
    # TODO: 实现
    raise NotImplementedError


@app.get("/api/v1/health")
async def health():
    return {"status": "ok"}
