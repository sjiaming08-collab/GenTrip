"""Plan Run StateGraph with turn orchestration and auto-relax."""

from langgraph.graph import END, StateGraph

from .nodes.auto_relax import auto_relax
from .nodes.constraint_extract import constraint_extract
from .nodes.geo_resolve import geo_resolve
from .nodes.poi_retrieve import poi_retrieve
from .nodes.reject_reply import reject_reply
from .nodes.route_evaluate import route_evaluate
from .nodes.route_generate import route_generate
from .nodes.route_present import route_present
from .nodes.route_validate import route_validate
from .nodes.turn_orchestrate import turn_orchestrate
from .state import GraphState


def _route_after_turn(state: GraphState) -> str:
    return state.get("turn_mode", "plan")


def _route_after_validate(state: GraphState) -> str:
    if not state.get("valid_routes") and int(state.get("relax_attempt", 0)) < 1:
        return "auto_relax"
    return "route_evaluate"


def build_plan_graph():
    graph = StateGraph(GraphState)

    graph.add_node("turn_orchestrate", turn_orchestrate)
    graph.add_node("constraint_extract", constraint_extract)
    graph.add_node("geo_resolve", geo_resolve)
    graph.add_node("poi_retrieve", poi_retrieve)
    graph.add_node("route_generate", route_generate)
    graph.add_node("route_validate", route_validate)
    graph.add_node("auto_relax", auto_relax)
    graph.add_node("route_evaluate", route_evaluate)
    graph.add_node("route_present", route_present)
    graph.add_node("reject_reply", reject_reply)

    graph.set_entry_point("turn_orchestrate")
    graph.add_conditional_edges(
        "turn_orchestrate",
        _route_after_turn,
        {
            "plan": "constraint_extract",
            "replan": "constraint_extract",
            "reject": "reject_reply",
        },
    )

    graph.add_edge("constraint_extract", "geo_resolve")
    graph.add_edge("geo_resolve", "poi_retrieve")
    graph.add_edge("poi_retrieve", "route_generate")
    graph.add_edge("route_generate", "route_validate")
    graph.add_conditional_edges(
        "route_validate",
        _route_after_validate,
        {
            "auto_relax": "auto_relax",
            "route_evaluate": "route_evaluate",
        },
    )
    graph.add_edge("auto_relax", "poi_retrieve")
    graph.add_edge("route_evaluate", "route_present")
    graph.add_edge("route_present", END)
    graph.add_edge("reject_reply", END)

    return graph


# Backward-compatible public name used by tests and services.
def build_plan_graph_cold():
    return build_plan_graph()


def create_plan_agent():
    return build_plan_graph().compile()
