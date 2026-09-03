"""Single structured LLM call for semantic activity blueprints."""

from pydantic import ValidationError

from .client import get_llm_client
from .exceptions import LLMParseError
from .prompts.activity_blueprint import SYSTEM_PROMPT, build_user_prompt
from ..models.blueprint import ActivitySlot, BlueprintDrafts, ItineraryBlueprint
from ..models.constraints import Constraints


async def generate_blueprint_drafts_with_meta(
    constraints: Constraints,
    *,
    start_at: str,
    return_by: str,
    scene_type: str,
) -> tuple[list[ItineraryBlueprint], dict]:
    client = get_llm_client()
    try:
        if hasattr(client, "chat_json_with_meta"):
            raw, meta = await client.chat_json_with_meta(
                SYSTEM_PROMPT,
                build_user_prompt(
                    constraints,
                    start_at=start_at,
                    return_by=return_by,
                    scene_type=scene_type,
                ),
                operation="activity_blueprint",
                temperature=0.2,
            )
        else:
            raw = await client.chat_json(
                SYSTEM_PROMPT,
                build_user_prompt(
                    constraints,
                    start_at=start_at,
                    return_by=return_by,
                    scene_type=scene_type,
                ),
            )
            meta = {"operation": "activity_blueprint", "status": "success"}
        result = BlueprintDrafts.model_validate(raw)
        blueprints = [
            ItineraryBlueprint(
                blueprint_id=f"bp-{draft.style}",
                style=draft.style,
                scene_type=scene_type,
                start_at=start_at,
                return_by=return_by,
                slots=[
                    ActivitySlot(
                        slot_id=slot.slot_id,
                        role=slot.role,
                        required=slot.role == "anchor",
                        domain=slot.domain,
                        categories=slot.categories,
                        activity_tags=slot.activity_tags,
                        time_window=slot.time_window,
                        duration_minutes=slot.duration_minutes,
                        spatial_policy=slot.spatial_policy,
                        source="inferred",
                    )
                    for slot in draft.slots
                ],
            )
            for draft in result.blueprints
        ]
        return blueprints, meta
    except ValidationError as exc:
        raise LLMParseError(f"activity blueprint schema 校验失败: {exc}") from exc
