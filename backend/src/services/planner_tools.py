"""Typed deterministic planner capabilities used by the graph orchestrator.

These are internal application tools, not Function Calling or MCP endpoints.
The graph owns call order and bounds; providers remain behind their existing
timeout/cache/fallback boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from ..models.blueprint import ItineraryBlueprint
from ..models.constraints import CompiledConstraints, Constraints
from ..models.retrieval import RetrievalPlan, RetrievalResult
from ..models.route import RouteLeg, RoutePlan, ScoredPoi
from .geo_resolver import GeoResolver, GeoScope
from .poi_retrieval import retrieve_by_plan_async
from .route_judge import judge_route
from .travel_matrix import select_route_leg
from .constraint_compiler import compile_constraints
from .blueprint_feasibility import compile_blueprint_feasibility


@dataclass(frozen=True)
class PoiSearchOutcome:
    result: RetrievalResult
    source: str
    degraded: bool
    cache_hit: bool


class GeoResolveTool:
    async def run(self, query: str, **kwargs) -> GeoScope:
        return await GeoResolver().resolve_geo_scope(query, **kwargs)


class ConstraintCompilerTool:
    def run(self, constraints: Constraints) -> tuple[Constraints, CompiledConstraints]:
        return compile_constraints(constraints)


class BlueprintFeasibilityTool:
    def run(
        self,
        blueprint: ItineraryBlueprint,
        constraints: Constraints,
        compiled: CompiledConstraints,
    ) -> tuple[ItineraryBlueprint | None, dict]:
        return compile_blueprint_feasibility(blueprint, constraints, compiled)


class PoiSearchTool:
    async def run(self, plan: RetrievalPlan, *, limit: int = 20) -> PoiSearchOutcome:
        result, source, degraded, cache_hit = await retrieve_by_plan_async(plan, limit=limit)
        return PoiSearchOutcome(result, source, degraded, cache_hit)


class PoiEnrichmentTool:
    """Assert the normalized evidence carried forward from a provider."""

    def run(self, pois: list[ScoredPoi], *, provider: str) -> list[ScoredPoi]:
        return [
            poi.model_copy(
                update={
                    "provider": poi.provider or provider,
                    "field_sources": poi.field_sources or {
                        "identity": provider,
                        "coordinates": provider,
                    },
                }
            )
            for poi in pois
        ]


class TravelMatrixTool:
    async def select_leg(
        self,
        origin: ScoredPoi,
        destination: ScoredPoi,
        *,
        budget_per_person: int,
        mobility_preferences: list[str] | None = None,
    ) -> RouteLeg:
        return await select_route_leg(
            origin,
            destination,
            budget_per_person=budget_per_person,
            mobility_preferences=mobility_preferences,
        )


class ScheduleTool:
    def inspect(self, blueprint: ItineraryBlueprint) -> dict:
        return {
            "slot_count": len(blueprint.slots),
            "required_slot_ids": [slot.slot_id for slot in blueprint.slots if slot.required],
            "meal_slot_ids": [slot.slot_id for slot in blueprint.slots if slot.role == "meal"],
        }


class PlanValidatorTool:
    def run(self, route: RoutePlan, constraints: dict, **kwargs):
        return judge_route(route, constraints, **kwargs)


class WeatherTool:
    def run(self, *, city: str | None = None) -> dict:
        return {
            "status": "unavailable",
            "city": city,
            "blocking": False,
            "source": "none",
        }
