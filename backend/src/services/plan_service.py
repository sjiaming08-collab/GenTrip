"""Plan 业务编排。"""

from ..graph.plan_graph import create_plan_agent
from ..graph.state import build_initial_state


class PlanService:
    def __init__(self) -> None:
        self._agent = create_plan_agent()

    async def run_plan(
        self,
        query: str,
        *,
        user_id: str | None = None,
        user_lat: float | None = None,
        user_lng: float | None = None,
        session_id: str | None = None,
    ) -> dict:
        initial = build_initial_state(
            query,
            user_id=user_id,
            user_lat=user_lat,
            user_lng=user_lng,
            session_id=session_id,
        )
        final_state = await self._agent.ainvoke(initial)
        return final_state
