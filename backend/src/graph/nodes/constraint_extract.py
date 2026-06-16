"""[1] constraint_extract — 约束提取 + 补全 assumptions。"""

from ...services.constraint_service import extract
from ..state import GraphState, phase_update


async def constraint_extract(state: GraphState) -> dict:
    constraints, assumptions = await extract(state)

    return phase_update(
        "constraint_extract",
        constraints=constraints.model_dump(mode="json"),
        assumptions=[a.model_dump(mode="json") for a in assumptions],
        constraint_embedding=None,
        plan_path="cold",
    )
