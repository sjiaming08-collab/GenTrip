"""LangGraph StateGraph 组装与条件分支

这是整个系统的调度核心。将各节点函数组装成状态图，
通过 add_conditional_edges 实现两分支路由。
"""

from langgraph.graph import StateGraph, END
from .state import GraphState

# ---- 节点函数引用 ----
from .nodes.intent_parse import intent_parse
from .nodes.search_cache import search_cache
from .nodes.match_score import match_score, decide_branch
from .nodes.adapt_template import adapt_template
from .nodes.full_generate import full_generate
from .nodes.render_output import render_output
from .nodes.feedback import process_feedback


def build_route_graph() -> StateGraph:
    """
    构建路线规划 LangGraph 状态图。

    流程图:
        intent_parse → search_cache → match_score
                                        │
                           ┌────────────┼────────────┐
                           │ score≥0.75             │ score<0.75
                           ▼                         ▼
                     adapt_template            full_generate
                           │                         │
                           └──────────┬──────────────┘
                                      ▼
                                 render_output
                                      │
                                      ▼
                               process_feedback
                                      │
                                      ▼
                                     END
    """
    graph = StateGraph(GraphState)

    # ---- 注册节点 ----
    graph.add_node("intent_parse", intent_parse)
    graph.add_node("search_cache", search_cache)
    graph.add_node("match_score", match_score)
    graph.add_node("adapt_template", adapt_template)
    graph.add_node("full_generate", full_generate)
    graph.add_node("render_output", render_output)
    graph.add_node("process_feedback", process_feedback)

    # ---- 边 ----
    graph.set_entry_point("intent_parse")
    graph.add_edge("intent_parse", "search_cache")
    graph.add_edge("search_cache", "match_score")

    # ---- 条件分支（核心） ----
    graph.add_conditional_edges(
        "match_score",
        decide_branch,            # 返回 "adapt" 或 "generate"
        {
            "adapt": "adapt_template",
            "generate": "full_generate",
        },
    )

    # ---- 汇合 ----
    graph.add_edge("adapt_template", "render_output")
    graph.add_edge("full_generate", "render_output")
    graph.add_edge("render_output", "process_feedback")
    graph.add_edge("process_feedback", END)

    return graph


def create_route_planner():
    """创建编译后的路线规划 Agent"""
    workflow = build_route_graph()
    return workflow.compile()
