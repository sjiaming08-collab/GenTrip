"""API DTO。"""

from typing import Optional

from pydantic import BaseModel, Field


class PlanRequest(BaseModel):
    query: str = Field(min_length=1)
    user_id: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    session_id: Optional[str] = None


class PlanResponse(BaseModel):
    run_id: str
    run_status: str
    plan_path: Optional[str]
    assumptions: list[dict]
    route_results: list[dict]
    presentation: Optional[dict]
    current_phase: str
