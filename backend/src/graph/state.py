"""GraphState — LangGraph 节点间的数据契约

每个节点读取 state 中的字段，处理后返回部分更新（PartialState）。
LangGraph 自动合并 reducer。
"""

from typing import TypedDict, Optional, Annotated
from langgraph.graph.message import add_messages
from ..models.intent import RouteIntent
from ..models.poi import ScoredPoi
from ..models.route import RoutePlan, RoutePlanResult, RouteFeedback
from ..models.template import RouteTemplate


class GraphState(TypedDict, total=False):
    """LangGraph 全局状态。字段按节点顺序排列。"""

    # ===== 输入 =====
    user_query: str                          # ① 用户原始 NL 输入
    user_id: Optional[str]                   # 用户标识
    user_lat: Optional[float]                # 用户当前纬度
    user_lng: Optional[float]                # 用户当前经度

    # ===== intent_parse 输出 =====
    route_intent: Optional[RouteIntent]      # ② LLM 解析后的结构化意图

    # ===== search_cache 输出 =====
    query_embedding: Optional[list[float]]   # ③ 查询向量 (512-dim)
    candidate_templates: list[RouteTemplate] # ③ 检索到的 top-K 模板

    # ===== match_score 输出 =====
    best_template: Optional[RouteTemplate]   # ④ 最佳匹配模板
    match_score: float                       # ④ 匹配分数 [0.0, 1.0]
    branch: str                              # ④ "adapt" | "generate"

    # ===== full_generate 中间产物 =====
    candidate_pois: list[ScoredPoi]          # POI 候选 (Top-30)

    # ===== 最终输出 =====
    route_result: Optional[RoutePlanResult]  # ⑤ 生成的路线

    # ===== 日志 / 流式推送 =====
    messages: Annotated[list, add_messages]  # SSE 流式消息累积
    current_phase: str                       # 当前阶段 (SSE 推送用)
    error: Optional[str]                     # 错误信息

    # ===== 反馈循环 =====
    feedback: Optional[RouteFeedback]        # ⑥ 用户反馈
    feedback_processed: bool                 # 反馈是否已处理
