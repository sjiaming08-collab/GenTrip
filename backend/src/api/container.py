"""Application-scoped service instances shared by HTTP and SSE routers."""

from ..services.plan_service import PlanService


plan_service = PlanService()
