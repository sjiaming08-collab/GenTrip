"""Plan Run StateGraph with turn orchestration, auto-relax, and replan."""

from langgraph.graph import END, StateGraph

from ..config import settings
from ..runtime.stage_observer import observe_node

from .nodes.activity_blueprint import activity_blueprint
from .nodes.blueprint_compile import blueprint_compile
from .nodes.auto_relax import auto_relax
from .nodes.bundle_rerank import bundle_rerank
from .nodes.constraint_extract import constraint_extract
from .nodes.constraint_compile import constraint_compile
from .nodes.geo_resolve import geo_resolve
from .nodes.failure_directed_repair import failure_directed_repair
from .nodes.lock_confirmed import lock_confirmed
from .nodes.local_optimize import local_optimize
from .nodes.partial_retrieval import partial_retrieval
from .nodes.planning_decision import planning_decision
from .nodes.planning_reply import planning_reply
from .nodes.poi_retrieve import poi_retrieve
from .nodes.reject_reply import reject_reply
from .nodes.render_diff import render_diff
from .nodes.replan_parse import replan_parse
from .nodes.route_evaluate import route_evaluate
from .nodes.route_bundle_ingest import route_bundle_ingest
from .nodes.route_bundle_search import route_bundle_search
from .nodes.route_generate import route_generate
from .nodes.route_present import route_present
from .nodes.route_validate import route_validate
from .nodes.turn_orchestrate import turn_orchestrate
from .nodes.validate_delta import validate_delta
from .state import GraphState


RESUMABLE_NODES = frozenset({
    "turn_orchestrate",
    "constraint_extract",
    "constraint_compile",
    "planning_decision",
    "planning_reply",
    "route_bundle_search",
    "bundle_rerank",
    "route_bundle_ingest",
    "geo_resolve",
    "activity_blueprint",
    "blueprint_compile",
    "poi_retrieve",
    "route_generate",
    "route_validate",
    "auto_relax",
    "failure_directed_repair",
    "route_evaluate",
    "route_present",
    "replan_parse",
    "lock_confirmed",
    "partial_retrieval",
    "local_optimize",
    "validate_delta",
    "render_diff",
    "reject_reply",
    "resume_finalize",
})

_TURN_TARGETS = {
    "plan": "constraint_extract",
    "replan": "replan_parse",
    "reject": "reject_reply",
}


def _route_after_turn(state: GraphState) -> str:
    return state.get("turn_mode", "plan")


def _route_after_constraint(state: GraphState) -> str:
    if state.get("turn_mode") == "reject":
        return "reject_reply"
    return "constraint_compile" if settings.constraint_compiler_enabled else "planning_decision"


def _route_after_validate(state: GraphState) -> str:
    if not state.get("valid_routes"):
        attempt_limit = 2 if settings.failure_directed_repair_enabled else 1
        if int(state.get("relax_attempt", 0)) < attempt_limit:
            return "failure_directed_repair" if settings.failure_directed_repair_enabled else "auto_relax"
    if not state.get("valid_routes"):
        return "planning_reply"
    if state.get("plan_path") == "hot" and state.get("valid_routes"):
        return "bundle_rerank"
    return "route_evaluate"


def _route_after_bundle_search(state: GraphState) -> str:
    return "route_validate" if state.get("plan_path") == "hot" else "geo_resolve"


def _route_after_geo_resolve(_state: GraphState) -> str:
    return "activity_blueprint" if settings.planner_blueprint_enabled else "poi_retrieve"


def _route_after_planning_decision(state: GraphState) -> str:
    status = (state.get("planning_decision") or {}).get("status")
    return "planning_reply" if status in {"clarification_required", "infeasible"} else "route_bundle_search"


def _route_after_replan_parse(state: GraphState) -> str:
    # Broad/schedule revisions use the full planner while retaining replan
    # identity; slot-only edits use the local optimization subgraph.
    operations = state.get("replan_operations") or []
    op = state.get("replan_operation") or {}
    if (
        state.get("recompute_scope") in {"schedule_route", "global_rebuild"}
        or op.get("type") == "change_pref"
        or any(item.get("type") == "change_pref" for item in operations)
        or state.get("turn_mode") == "plan"
    ):
        return "constraint_extract"
    return "lock_confirmed"


def _route_after_delta(state: GraphState) -> str:
    return "render_diff"


def _route_after_repair(state: GraphState) -> str:
    return "poi_retrieve" if state.get("repair_applied") else "planning_reply"


def next_node_after_phase(phase: str, state: GraphState) -> str | None:
    """Return the node that a durable retry must execute after a checkpoint."""
    if phase == "turn_orchestrate":
        return _TURN_TARGETS.get(_route_after_turn(state), "constraint_extract")
    if phase == "constraint_extract":
        return _route_after_constraint(state)
    if phase == "constraint_compile":
        return "planning_decision"
    if phase == "planning_decision":
        return _route_after_planning_decision(state)
    if phase == "route_bundle_search":
        return _route_after_bundle_search(state)
    if phase == "geo_resolve":
        return _route_after_geo_resolve(state)
    if phase == "route_validate":
        return _route_after_validate(state)
    if phase == "failure_directed_repair":
        return _route_after_repair(state)
    if phase == "replan_parse":
        return _route_after_replan_parse(state)
    if phase == "validate_delta":
        return _route_after_delta(state)
    direct = {
        "activity_blueprint": "blueprint_compile" if settings.blueprint_feasibility_enabled else "poi_retrieve",
        "blueprint_compile": "poi_retrieve",
        "poi_retrieve": "route_generate",
        "route_generate": "route_validate",
        "auto_relax": "poi_retrieve",
        "route_evaluate": "route_bundle_ingest",
        "route_bundle_ingest": "route_present",
        "bundle_rerank": "route_present",
        "lock_confirmed": "partial_retrieval",
        "partial_retrieval": "local_optimize",
        "local_optimize": "validate_delta",
    }
    if phase in {"planning_reply", "route_present", "render_diff", "reject_reply"}:
        return "resume_finalize"
    return direct.get(phase)


def _resume_dispatch(state: GraphState) -> dict:
    return {}


def _resume_route(state: GraphState) -> str:
    requested = state.get("resume_next_node") or "turn_orchestrate"
    return requested if requested in RESUMABLE_NODES else "turn_orchestrate"


def _resume_finalize(_state: GraphState) -> dict:
    return {}


def build_plan_graph():
    graph = StateGraph(GraphState)

    def add_node(name, node):
        graph.add_node(name, observe_node(name, node))

    graph.add_node("resume_dispatch", _resume_dispatch)
    graph.add_node("resume_finalize", _resume_finalize)

    # --- Turn Orchestrator ---
    add_node("turn_orchestrate", turn_orchestrate)

    # --- Plan path ---
    add_node("constraint_extract", constraint_extract)
    add_node("constraint_compile", constraint_compile)
    add_node("planning_decision", planning_decision)
    add_node("planning_reply", planning_reply)
    add_node("route_bundle_search", route_bundle_search)
    add_node("bundle_rerank", bundle_rerank)
    add_node("route_bundle_ingest", route_bundle_ingest)
    add_node("geo_resolve", geo_resolve)
    add_node("activity_blueprint", activity_blueprint)
    add_node("blueprint_compile", blueprint_compile)
    add_node("poi_retrieve", poi_retrieve)
    add_node("route_generate", route_generate)
    add_node("route_validate", route_validate)
    add_node("auto_relax", auto_relax)
    add_node("failure_directed_repair", failure_directed_repair)
    add_node("route_evaluate", route_evaluate)
    add_node("route_present", route_present)

    # --- Replan path ---
    add_node("replan_parse", replan_parse)
    add_node("lock_confirmed", lock_confirmed)
    add_node("partial_retrieval", partial_retrieval)
    add_node("local_optimize", local_optimize)
    add_node("validate_delta", validate_delta)
    add_node("render_diff", render_diff)

    # --- Reject ---
    add_node("reject_reply", reject_reply)

    # --- Entry ---
    graph.set_entry_point("resume_dispatch")
    graph.add_conditional_edges(
        "resume_dispatch",
        _resume_route,
        {name: name for name in RESUMABLE_NODES},
    )
    graph.add_edge("resume_finalize", END)

    # --- Turn routing ---
    graph.add_conditional_edges(
        "turn_orchestrate",
        _route_after_turn,
        {
            "plan": "constraint_extract",
            "replan": "replan_parse",
            "reject": "reject_reply",
        },
    )

    # --- Plan cold path ---
    graph.add_conditional_edges(
        "constraint_extract",
        _route_after_constraint,
        {
            "constraint_compile": "constraint_compile",
            "planning_decision": "planning_decision",
            "reject_reply": "reject_reply",
        },
    )
    graph.add_edge("constraint_compile", "planning_decision")
    graph.add_conditional_edges(
        "planning_decision",
        _route_after_planning_decision,
        {"planning_reply": "planning_reply", "route_bundle_search": "route_bundle_search"},
    )
    graph.add_edge("planning_reply", END)
    graph.add_conditional_edges(
        "route_bundle_search",
        _route_after_bundle_search,
        {"geo_resolve": "geo_resolve", "route_validate": "route_validate"},
    )
    graph.add_conditional_edges(
        "geo_resolve",
        _route_after_geo_resolve,
        {"activity_blueprint": "activity_blueprint", "poi_retrieve": "poi_retrieve"},
    )
    graph.add_conditional_edges(
        "activity_blueprint",
        lambda _state: "blueprint_compile" if settings.blueprint_feasibility_enabled else "poi_retrieve",
        {"blueprint_compile": "blueprint_compile", "poi_retrieve": "poi_retrieve"},
    )
    graph.add_edge("blueprint_compile", "poi_retrieve")
    graph.add_edge("poi_retrieve", "route_generate")
    graph.add_edge("route_generate", "route_validate")
    graph.add_conditional_edges(
        "route_validate",
        _route_after_validate,
        {
            "auto_relax": "auto_relax",
            "failure_directed_repair": "failure_directed_repair",
            "planning_reply": "planning_reply",
            "route_evaluate": "route_evaluate",
            "bundle_rerank": "bundle_rerank",
        },
    )
    graph.add_edge("auto_relax", "poi_retrieve")
    graph.add_conditional_edges(
        "failure_directed_repair",
        _route_after_repair,
        {"poi_retrieve": "poi_retrieve", "planning_reply": "planning_reply"},
    )
    graph.add_edge("route_evaluate", "route_bundle_ingest")
    graph.add_edge("route_bundle_ingest", "route_present")
    graph.add_edge("bundle_rerank", "route_present")
    graph.add_edge("route_present", END)

    # --- Replan subgraph ---
    graph.add_conditional_edges(
        "replan_parse",
        _route_after_replan_parse,
        {"constraint_extract": "constraint_extract", "lock_confirmed": "lock_confirmed"},
    )
    graph.add_edge("lock_confirmed", "partial_retrieval")
    graph.add_edge("partial_retrieval", "local_optimize")
    graph.add_edge("local_optimize", "validate_delta")
    graph.add_conditional_edges(
        "validate_delta",
        _route_after_delta,
        {"render_diff": "render_diff"},
    )
    graph.add_edge("render_diff", END)

    # --- Reject ---
    graph.add_edge("reject_reply", END)

    return graph


# Backward-compatible public name used by tests and services.
def build_plan_graph_cold():
    return build_plan_graph()


def create_plan_agent():
    return build_plan_graph().compile()
