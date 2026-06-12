"""意图理解模块的数据模型 —— NL → 结构化约束"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class TripPurpose(str, Enum):
    DINING = "DINING"
    SIGHTSEEING = "SIGHTSEEING"
    SHOPPING = "SHOPPING"
    MIXED = "MIXED"


class CrowdTolerance(str, Enum):
    LOW = "LOW"         # 不想排队
    MEDIUM = "MEDIUM"   # 可少量排队
    HIGH = "HIGH"       # 不在意排队


class InferredPreferences(BaseModel):
    """LLM 从用户措辞中推断的隐式偏好"""
    party_context: Optional[str] = Field(
        default=None,
        description="同行情境: 和朋友/约会/带娃/独行/商务"
    )
    vibe_preference: Optional[str] = Field(
        default=None,
        description="氛围偏好: casual/romantic/quiet/lively"
    )
    instagrammable: Optional[bool] = Field(
        default=None,
        description="是否偏好网红打卡型 POI"
    )
    local_hidden_gem: Optional[bool] = Field(
        default=None,
        description="是否偏好本地老店/隐藏小店"
    )
    pace_preference: Optional[str] = Field(
        default=None,
        description="节奏偏好: relaxed/normal/rushed"
    )


class RouteConstraints(BaseModel):
    """结构化约束条件，每个字段 null = 用户未指定"""
    time_budget_minutes: Optional[int] = Field(
        default=None, description="最大总时长（分钟）, e.g. 180"
    )
    district: Optional[str] = Field(
        default=None, description="区域名称, e.g. 徐汇区"
    )
    preferred_cuisines: Optional[list[str]] = Field(
        default=None, description="偏好品类, e.g. ['火锅','日料']"
    )
    budget_per_person: Optional[int] = Field(
        default=None, description="人均预算上限（元）"
    )
    poi_count: Optional[int] = Field(
        default=None, description="期望 POI 数量"
    )
    crowd_tolerance: Optional[CrowdTolerance] = Field(
        default=None, description="排队容忍度"
    )


class RouteIntent(BaseModel):
    """意图理解节点的输出"""
    purpose: TripPurpose = Field(description="出行目的")
    raw_query: str = Field(description="用户原始输入")
    constraints: RouteConstraints = Field(description="结构化约束")
    preferences: InferredPreferences = Field(
        default_factory=InferredPreferences, description="隐式偏好"
    )
