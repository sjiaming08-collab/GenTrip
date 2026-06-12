"""POI 数据模型"""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class TravelMode(str, Enum):
    WALK = "WALK"
    TRANSIT = "TRANSIT"
    BIKE = "BIKE"
    TAXI = "TAXI"
    START = "START"       # 第一站（起点）


class GeoPoint(BaseModel):
    """地理坐标"""
    lat: float
    lng: float


class PoiSummary(BaseModel):
    """POI 摘要（嵌入到路线 stop 中）"""
    id: str
    name: str
    category: str                    # e.g. "火锅"
    overall_rating: float            # 0.0-5.0
    avg_price_per_person: int        # 人均 CNY
    address: str
    latitude: float
    longitude: float
    detail_url: Optional[str] = None  # 点评 deep link
    cover_image_url: Optional[str] = None
    phone_number: Optional[str] = None


class PoiEntity(PoiSummary):
    """POI 完整实体（数据库存储）"""
    sub_category: Optional[str] = None
    taste_rating: Optional[float] = None
    service_rating: Optional[float] = None
    environment_rating: Optional[float] = None
    shop_hours: Optional[dict] = None     # {"mon":"10:00-22:00", ...}
    comment_count: int = 0
    crowd_index: Optional[float] = None   # 拥挤指数
    district: Optional[str] = None
    area: Optional[str] = None
    # ---- 向量 ----
    embedding: Optional[list[float]] = None  # pgvector: 512-dim
    # ---- 时间戳 ----
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class ScoredPoi(BaseModel):
    """带多维评分的 POI"""
    poi: PoiEntity
    relevance_score: float = 0.0     # 语义相关性 [0,1]
    quality_score: float = 0.0       # 品质评分 [0,1]
    personalization_score: float = 0.0  # 个性化匹配 [0,1]
    crowd_penalty: float = 0.0       # 拥挤惩罚 [0,1]
    distance_penalty: float = 0.0    # 距离惩罚 [0,1]
    composite_score: float = 0.0     # 综合评分
