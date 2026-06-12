"""路线规划数据模型"""

from datetime import datetime, time
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
from .poi import PoiSummary, TravelMode


class RouteSource(str, Enum):
    """路线来源"""
    CACHE_HIT = "CACHE_HIT"           # 直接命中知识库
    CACHE_ADAPTED = "CACHE_ADAPTED"    # 模板适配
    FRESH_GENERATED = "FRESH_GENERATED"  # 全新生成


class ItineraryStop(BaseModel):
    """路线中的一个停靠点"""
    sequence: int
    poi: PoiSummary
    arrival_time: time
    departure_time: time
    visit_duration_min: int
    travel_time_from_prev_min: int = 0
    travel_mode: TravelMode = TravelMode.START
    ai_tip: Optional[str] = None         # LLM 生成的贴士
    estimated_queue_min: Optional[int] = None
    reservation_url: Optional[str] = None


class RouteMetadata(BaseModel):
    """路线元数据"""
    total_duration_min: int
    total_travel_time_min: int
    total_pois: int
    average_poi_score: float
    start_time: time
    end_time: time
    weather_note: Optional[str] = None


class RoutePlan(BaseModel):
    """路线方案的完整内部表示"""
    route_id: Optional[str] = None       # 持久化后回填
    plan_name: str                       # LLM 生成: "徐汇火锅甜品半日游"
    summary: str                         # 一句话总结
    source: RouteSource = RouteSource.FRESH_GENERATED
    stops: list[ItineraryStop]
    metadata: RouteMetadata
    map_deep_link: Optional[str] = None  # 高德地图 deep link
    created_at: datetime = Field(default_factory=datetime.now)


class RoutePlanResult(BaseModel):
    """ExperienceReuseEngine 的返回值，包装了来源信息"""
    route: RoutePlan
    source: RouteSource
    matched_template_id: Optional[str] = None  # 命中的模板ID（如有）


class RouteFeedback(BaseModel):
    """用户反馈"""
    route_id: str
    overall_score: float = Field(ge=1.0, le=5.0)
    poi_ratings: Optional[dict[str, float]] = None  # poi_id → score
    comments: Optional[str] = None
    actual_pois_visited: Optional[list[str]] = None  # 实际走了哪些
