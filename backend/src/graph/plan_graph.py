"""Plan Run 冷路径 StateGraph — Step A。"""

from langgraph.graph import END, StateGraph

from .nodes.constraint_extract import constraint_extract
from .nodes.poi_retrieve import poi_retrieve
from .nodes.route_evaluate import route_evaluate
from .nodes.route_generate import route_generate
from .nodes.route_present import route_present
from .nodes.route_validate import route_validate
from .state import GraphState


def build_plan_graph_cold():
    """
    冷路径六段：
      constraint_extract → poi_retrieve → route_generate
        → route_validate → route_evaluate → route_present
    """
    graph = StateGraph(GraphState)

    graph.add_node("constraint_extract", constraint_extract)
    graph.add_node("poi_retrieve", poi_retrieve)
    graph.add_node("route_generate", route_generate)
    graph.add_node("route_validate", route_validate)
    graph.add_node("route_evaluate", route_evaluate)
    graph.add_node("route_present", route_present)

    graph.set_entry_point("constraint_extract")
    graph.add_edge("constraint_extract", "poi_retrieve")
    graph.add_edge("poi_retrieve", "route_generate")
    graph.add_edge("route_generate", "route_validate")
    graph.add_edge("route_validate", "route_evaluate")
    graph.add_edge("route_evaluate", "route_present")
    graph.add_edge("route_present", END)

    return graph


def create_plan_agent():
    return build_plan_graph_cold().compile()
