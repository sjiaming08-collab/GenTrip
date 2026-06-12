"""POI 检索工具 — LangChain Tool 封装

将 BasePoiRepository 的能力暴露为 LLM 可调用的 Tool，
使 LLM 可以在路线规划时自主搜索 POI。
"""

from langchain_core.tools import tool


# ============================================================
# Tool 抽象接口 (具体实现注入 BasePoiRepository)
# ============================================================

@tool
async def search_poi_by_filters(
    district: str = "",
    categories: str = "",
    max_price: int = 0,
    min_rating: float = 0.0,
    limit: int = 30,
) -> str:
    """
    按条件检索 POI 列表。

    Args:
        district: 区域名称，如 "徐汇区"、"静安区"
        categories: 品类，逗号分隔，如 "火锅,日料"
        max_price: 人均价格上限 (元)
        min_rating: 最低评分 (0-5)
        limit: 最大返回数
    Returns:
        JSON 格式的 POI 列表
    """
    # TODO: 注入 poi_repository 实现
    raise NotImplementedError


@tool
async def get_poi_detail(poi_id: str) -> str:
    """
    获取单个 POI 详情。

    Args:
        poi_id: POI ID
    Returns:
        JSON 格式的 POI 完整信息
    """
    # TODO: 注入 poi_repository 实现
    raise NotImplementedError


@tool
async def estimate_distance(
    lat1: float, lng1: float,
    lat2: float, lng2: float,
    mode: str = "walk",
) -> str:
    """
    估算两点间距离和出行时间。

    Args:
        lat1, lng1: 起点坐标
        lat2, lng2: 终点坐标
        mode: "walk" | "transit" | "taxi"
    Returns:
        JSON: {"distance_meters": int, "duration_minutes": int}
    """
    # TODO: 实现 (Haversine 近似 + 模式系数)
    raise NotImplementedError


# 注册给 LLM 可用的 tool 列表
ROUTE_PLANNING_TOOLS = [
    search_poi_by_filters,
    get_poi_detail,
    estimate_distance,
]
