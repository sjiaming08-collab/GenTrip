"""路线模板（知识库核心）"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class RouteTemplate(BaseModel):
    """预计算/缓存的路线模板

    存储于 PostgreSQL，query_embedding 使用 pgvector 做语义检索。
    route_json 存储完整的 RoutePlan JSON。
    """
    id: Optional[str] = None            # UUID, 数据库生成

    # ---- 检索字段 ----
    scenario: str                       # "周末逛吃", "约会晚餐", "亲子一日游"
    district: Optional[str] = None      # "徐汇区", None=跨区
    typical_duration_min: int           # e.g. 180
    typical_budget: int                 # e.g. 200
    cuisine_tags: list[str] = Field(    # ["火锅", "日料"]
        default_factory=list
    )
    search_text: str = ""               # 用于生成向量的原始文本

    # ---- 语义向量 (pgvector, 512-dim) ----
    query_embedding: Optional[list[float]] = None

    # ---- 路线内容 ----
    route_json: str = ""                # RoutePlan.model_dump_json()

    # ---- 质量指标 ----
    use_count: int = 0
    positive_feedback_count: int = 0
    avg_rating: float = 4.0
    active: bool = True

    # ---- 时间戳 ----
    generated_at: datetime = Field(default_factory=datetime.now)
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None  # 过期时间（POI数据可能变）
