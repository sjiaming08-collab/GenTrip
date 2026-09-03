"""Create bounded semantic activity blueprints before POI retrieval."""

from ...services.activity_blueprint_service import generate_blueprints_with_meta
from ..state import GraphState, llm_call_from_meta, phase_update


async def activity_blueprint(state: GraphState) -> dict:
    blueprints, llm_meta = await generate_blueprints_with_meta(state)
    llm_call = llm_call_from_meta(
        "activity_blueprint",
        llm_meta,
        fallback_used=bool(llm_meta.get("fallback_used")),
        source=llm_meta.get("source"),
    )
    slot_assumptions: list[dict] = []
    explicit_slots = 0
    inferred_slots = 0
    for blueprint in blueprints:
        for slot in blueprint.slots:
            if slot.source == "explicit":
                explicit_slots += 1
            else:
                inferred_slots += 1
            if slot.assumption_message:
                slot_assumptions.append(
                    {
                        "slot": f"activity_slot:{slot.slot_id}",
                        "assumed_value": ",".join(slot.categories) or slot.role,
                        "source": "activity_policy" if slot.source == "policy" else "scene_inferred",
                        "message": slot.assumption_message,
                        "overridable": True,
                    }
                )
    update = phase_update(
        "activity_blueprint",
        summary=(
            f"blueprints={len(blueprints)} explicit_slots={explicit_slots} "
            f"inferred_slots={inferred_slots}"
        ),
        activity_blueprints=[item.model_dump(mode="json") for item in blueprints],
        selected_blueprint_id=blueprints[0].blueprint_id if blueprints else None,
        assumptions=slot_assumptions,
        llm_calls=[llm_call],
    )
    update["phase_log"][0].update(
        {
            "blueprint_count": len(blueprints),
            "explicit_slot_count": explicit_slots,
            "inferred_slot_count": inferred_slots,
            "llm_operation": llm_call["operation"],
            "llm_status": llm_call["status"],
        }
    )
    return update
