"""HTTP 路由。"""

from fastapi import APIRouter, HTTPException

from ..config import settings
from ..services.plan_service import PlanService
from .schemas import PlanRequest, PlanResponse

router = APIRouter()
_plan_service = PlanService()


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "app": settings.app_name,
        "step": "A-cold-path",
    }


@router.post("/routes/plan", response_model=PlanResponse)
async def plan_route(request: PlanRequest):
    state = await _plan_service.run_plan(
        request.query,
        user_id=request.user_id,
        user_lat=request.lat,
        user_lng=request.lng,
        session_id=request.session_id,
    )
    if state.get("run_status") != "completed":
        raise HTTPException(
            status_code=500,
            detail=state.get("error") or "plan_run_failed",
        )
    return PlanResponse(
        run_id=state["run_id"],
        run_status=state["run_status"],
        plan_path=state.get("plan_path"),
        assumptions=state.get("assumptions", []),
        route_results=state.get("route_results", []),
        presentation=state.get("presentation"),
        current_phase=state.get("current_phase", "done"),
    )
