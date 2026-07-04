"""[1] constraint_extract — 约束提取 + 补全 assumptions。"""

from ...services.constraint_service import extract_with_meta
from ..state import GraphState, llm_call_from_meta, phase_update


async def constraint_extract(state: GraphState) -> dict:
    constraints, assumptions, llm_meta = await extract_with_meta(state)
    llm_call = llm_call_from_meta(
        "constraint_extract",
        llm_meta,
        fallback_used=bool(llm_meta.get("fallback_used")),
    )

    update = phase_update(
        "constraint_extract",
        summary="extracted constraints",
        constraints=constraints.model_dump(mode="json"),
        assumptions=[a.model_dump(mode="json") for a in assumptions],
        constraint_embedding=None,
        plan_path="cold",
        llm_calls=[llm_call],
    )
    update["phase_log"][0].update({
        "llm_operation": llm_call["operation"],
        "llm_status": llm_call["status"],
    })
    return update
