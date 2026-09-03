"""Generate semantic activity blueprints and apply deterministic slot policy."""

from __future__ import annotations

import re
from copy import deepcopy

from pydantic import ValidationError

from ..config import settings
from ..graph.state import GraphState
from ..llm.activity_blueprint_llm import generate_blueprint_drafts_with_meta
from ..llm.exceptions import LLMError, failure_meta
from ..models.blueprint import ActivitySlot, ItineraryBlueprint, SlotTimeWindow
from ..models.constraints import Constraints, IntentDomain
from .poi_query_parser import domain_specs_from_constraints, order_domains_for_query
from .constraint_compiler import compile_constraints

_NO_MEAL_RE = re.compile(r"(?:不|别|无需|不要)(?:安排)?(?:吃饭|用餐|餐饮|午餐|晚餐)")
_NO_COFFEE_RE = re.compile(r"(?:不|别|无需|不要)(?:安排)?(?:咖啡|下午茶)")

_DOMAIN_CONCEPTS: dict[IntentDomain, dict[str, list[str]]] = {
    IntentDomain.SIGHTSEEING: {
        "balanced": ["城市漫步", "文化参观", "公园景观"],
        "experiential": ["街区探索", "文化体验", "观景打卡"],
    },
    IntentDomain.DINING: {
        "balanced": ["正餐", "地方风味"],
        "experiential": ["特色餐饮", "甜品饮品"],
    },
    IntentDomain.SHOPPING: {
        "balanced": ["商圈漫游", "特色店铺"],
        "experiential": ["设计商店", "市集探索"],
    },
    IntentDomain.LEISURE: {
        "balanced": ["休闲体验", "轻松娱乐"],
        "experiential": ["沉浸体验", "现场活动"],
    },
}


def _clock(value: str | None, default: int) -> int:
    if not value:
        return default
    hour, minute = value.split(":", 1)
    return int(hour) * 60 + int(minute)


def _hhmm(value: int) -> str:
    value = max(0, min(value, 23 * 60 + 59))
    return f"{value // 60:02d}:{value % 60:02d}"


def _window(constraints: Constraints) -> tuple[int, int]:
    duration = constraints.time_budget_minutes or 180
    if constraints.start_at:
        start = _clock(constraints.start_at, 10 * 60)
        end = _clock(constraints.return_by, start + duration) if constraints.return_by else start + duration
    elif constraints.return_by:
        end = _clock(constraints.return_by, 18 * 60)
        start = max(0, end - duration)
    else:
        start = 10 * 60
        end = start + duration
    return start, min(end, 23 * 60 + 59)


def _scene_type(constraints: Constraints) -> str:
    if constraints.scene_type in {"solo", "couple", "friends", "family"}:
        return constraints.scene_type
    query = constraints.raw_query
    if re.search(r"情侣|约会|女朋友|男朋友|对象|爱人", query):
        return "couple"
    if re.search(r"亲子|孩子|小朋友|宝宝|一家人", query):
        return "family"
    if re.search(r"朋友|闺蜜|同学|聚会", query):
        return "friends"
    return "solo"


def _concept_slots(constraints: Constraints, style: str) -> list[ActivitySlot]:
    domains = order_domains_for_query(
        list(constraints.domains or [IntentDomain.SIGHTSEEING]),
        constraints.raw_query,
    )
    explicit_count = constraints.anchor_count_explicit
    category_preferences = {
        spec.domain: list(spec.categories or [])
        for spec in domain_specs_from_constraints(
            constraints.model_dump(mode="json"),
            constraints.raw_query,
        )
    }
    if explicit_count:
        target = explicit_count
    elif domains == [IntentDomain.DINING]:
        target = max(1, min(3, len(constraints.preferred_cuisines or [])))
    else:
        target = max(
            len(domains),
            min(3, max(1, constraints.poi_count_target or constraints.poi_count)),
        )
    domain_counts: dict[IntentDomain, int] = {}
    explicit_domains = {
        str(item.get("domain_hint"))
        for item in constraints.explicit_activities
        if item.get("modality") == "required" and item.get("domain_hint")
    }
    slots: list[ActivitySlot] = []
    for index in range(target):
        domain = domains[index % len(domains)]
        domain_index = domain_counts.get(domain, 0)
        domain_counts[domain] = domain_index + 1
        concepts = _DOMAIN_CONCEPTS[domain][style]
        preferred = category_preferences.get(domain) or []
        categories = [preferred[domain_index % len(preferred)]] if preferred else []
        concept = concepts[domain_index % len(concepts)]
        required = bool(explicit_count) or (
            domain.value in explicit_domains and domain_index == 0
        )
        slots.append(
            ActivitySlot(
                slot_id=f"{style}-anchor-{index + 1}",
                role="anchor",
                required=required,
                domain=domain,
                categories=categories,
                activity_tags=list(dict.fromkeys([*(constraints.activity_tags or []), concept])),
                duration_minutes=75 if style == "experiential" else 60,
                source="explicit" if required else "inferred",
                requirement_level="hard" if required else "optional",
                order_policy="fixed" if required else "flexible",
            )
        )
    return slots


def _optional_scene_slots(
    constraints: Constraints,
    *,
    style: str,
    scene_type: str,
    start: int,
    end: int,
) -> list[ActivitySlot]:
    if scene_type != "couple" or end - start < 360:
        return []
    slots: list[ActivitySlot] = []
    if not _NO_COFFEE_RE.search(constraints.raw_query):
        slots.append(
            ActivitySlot(
                slot_id=f"{style}-optional-tea",
                role="optional",
                required=False,
                domain=IntentDomain.DINING,
                categories=["咖啡馆" if style == "balanced" else "下午茶"],
                activity_tags=["约会", "安静"],
                duration_minutes=45,
                source="inferred",
                assumption_message="根据情侣全天场景加入可选下午茶",
            )
        )
    if end >= 17 * 60:
        slots.append(
            ActivitySlot(
                slot_id=f"{style}-optional-sunset",
                role="optional",
                required=False,
                domain=IntentDomain.SIGHTSEEING,
                categories=["日落观景"],
                activity_tags=["浪漫", "观景"],
                duration_minutes=45,
                source="inferred",
                assumption_message="根据情侣全天场景加入可选日落",
            )
        )
    return slots


def build_rule_blueprints(constraints: Constraints) -> list[ItineraryBlueprint]:
    """Create two deterministic fallbacks without naming any POI."""

    if not constraints.explicit_activities:
        constraints, _ = compile_constraints(constraints)

    start, end = _window(constraints)
    scene_type = _scene_type(constraints)
    blueprints: list[ItineraryBlueprint] = []
    for style in ("balanced", "experiential"):
        slots = _concept_slots(constraints, style)
        slots.extend(
            _optional_scene_slots(
                constraints,
                style=style,
                scene_type=scene_type,
                start=start,
                end=end,
            )
        )
        draft = ItineraryBlueprint(
            blueprint_id=f"bp-{style}",
            style=style,
            scene_type=scene_type,
            start_at=_hhmm(start),
            return_by=_hhmm(end),
            slots=slots[:8],
        )
        blueprints.append(apply_slot_policy(draft, constraints))
    return blueprints


def _meal_slot(style: str, meal: str) -> ActivitySlot:
    is_lunch = meal == "lunch"
    return ActivitySlot(
        slot_id=f"{style}-meal-{meal}",
        role="meal",
        required=False,
        domain=IntentDomain.DINING,
        categories=["午餐" if is_lunch else "晚餐"],
        time_window=SlotTimeWindow(
            start="11:30" if is_lunch else "17:30",
            end="13:30" if is_lunch else "19:30",
        ),
        duration_minutes=60,
        source="policy",
        requirement_level="policy",
        assumption_message=f"根据行程时段自动加入{'午餐' if is_lunch else '晚餐'}",
    )


def _insert_by_time(
    slots: list[ActivitySlot],
    slot: ActivitySlot,
    *,
    start: int,
    end: int,
    target: int,
) -> None:
    if not slots:
        slots.append(slot)
        return
    del end

    # A slot-count ratio breaks as soon as the LLM proposes activities with
    # different durations. Estimate the earliest arrival at every insertion
    # point, including a small transfer reserve, and keep the meal service
    # inside its hard window. POI-level travel is still calculated later.
    arrivals = [start]
    cursor = start
    for existing in slots:
        if existing.time_window is not None:
            cursor = max(cursor, _clock(existing.time_window.start, cursor))
        cursor += existing.duration_minutes + 15
        arrivals.append(cursor)

    window_end = (
        _clock(slot.time_window.end, target + slot.duration_minutes)
        if slot.time_window is not None
        else target + slot.duration_minutes
    )
    latest_start = window_end - slot.duration_minutes
    preferred_start = target - slot.duration_minutes // 2
    viable = [
        (index, arrival)
        for index, arrival in enumerate(arrivals)
        if arrival <= latest_start
    ]
    if viable:
        index = min(
            viable,
            key=lambda item: (abs(item[1] - preferred_start), -item[0]),
        )[0]
    else:
        index = 0
    slots.insert(index, slot)


def _insert_rest(slots: list[ActivitySlot], style: str) -> None:
    active = 0
    for index, slot in enumerate(list(slots)):
        if slot.role in {"meal", "rest"}:
            active = 0
            continue
        active += slot.duration_minutes
        if active >= 180 and index < len(slots) - 1:
            slots.insert(
                index + 1,
                ActivitySlot(
                    slot_id=f"{style}-rest-1",
                    role="rest",
                    required=False,
                    categories=["短暂休息"],
                    duration_minutes=20,
                    source="policy",
                    requirement_level="policy",
                    assumption_message="连续活动较久，自动加入短暂休息",
                ),
            )
            return


def _trim_to_limit(slots: list[ActivitySlot], limit: int = 8) -> list[ActivitySlot]:
    slots = list(slots)
    while len(slots) > limit:
        optional_index = next(
            (index for index in range(len(slots) - 1, -1, -1) if not slots[index].required),
            None,
        )
        if optional_index is not None:
            slots.pop(optional_index)
            continue
        rest_index = next(
            (index for index, item in enumerate(slots) if item.role == "rest"), None
        )
        if rest_index is not None:
            slots.pop(rest_index)
            continue
        break
    return slots[:limit]


def apply_slot_policy(
    blueprint: ItineraryBlueprint,
    constraints: Constraints,
) -> ItineraryBlueprint:
    """Insert service slots deterministically and enforce the station cap."""

    start, end = _window(constraints)
    slots = [deepcopy(slot) for slot in blueprint.slots if slot.role not in {"meal", "rest"}]
    has_dining_anchor = any(
        slot.role == "anchor"
        and slot.domain == IntentDomain.DINING
        and not any(
            light in " ".join(slot.categories)
            for light in ("咖啡", "下午茶", "甜品", "甜点", "酒吧", "饮品")
        )
        for slot in slots
    )
    if not _NO_MEAL_RE.search(constraints.raw_query) and not has_dining_anchor:
        if end - start >= 300 and start <= 13 * 60 + 30 and end >= 11 * 60 + 30:
            _insert_by_time(
                slots,
                _meal_slot(blueprint.style, "lunch"),
                start=start,
                end=end,
                target=12 * 60 + 30,
            )
        if start <= 17 * 60 + 30 and end >= 18 * 60 + 30:
            _insert_by_time(
                slots,
                _meal_slot(blueprint.style, "dinner"),
                start=start,
                end=end,
                target=18 * 60 + 30,
            )
    _insert_rest(slots, blueprint.style)
    slots = _trim_to_limit(slots)
    return blueprint.model_copy(
        update={
            "scene_type": _scene_type(constraints),
            "start_at": _hhmm(start),
            "return_by": _hhmm(end),
            "slots": slots,
        }
    )


def normalize_llm_blueprints(
    drafts: list[ItineraryBlueprint],
    constraints: Constraints,
) -> list[ItineraryBlueprint]:
    """Sanitize LLM concepts, supplement missing styles, then apply policy."""

    if not constraints.explicit_activities:
        constraints, _ = compile_constraints(constraints)

    fallback = {item.style: item for item in build_rule_blueprints(constraints)}
    normalized: list[ItineraryBlueprint] = []
    for style in ("balanced", "experiential"):
        draft = next((item for item in drafts if item.style == style), None)
        if draft is None:
            normalized.append(fallback[style])
            continue
        semantic_slots = []
        for slot in draft.slots:
            if slot.role not in {"anchor", "optional"} or not slot.categories:
                continue
            slot_id = slot.slot_id
            if not slot_id.startswith(f"{style}-"):
                slot_id = f"{style}-{slot_id}"
            semantic_slots.append(slot.model_copy(update={"slot_id": slot_id}))

        anchors = [slot for slot in semantic_slots if slot.role == "anchor"]
        if constraints.anchor_count_explicit:
            semantic_slots.extend(
                slot
                for slot in fallback[style].slots
                if slot.role == "anchor"
            )
        else:
            present_domains = {slot.domain for slot in anchors if slot.domain is not None}
            for domain in constraints.domains:
                if domain in present_domains:
                    continue
                supplement = next(
                    (
                        slot
                        for slot in fallback[style].slots
                        if slot.role == "anchor" and slot.domain == domain
                    ),
                    None,
                )
                if supplement is not None:
                    semantic_slots.append(supplement)
                    present_domains.add(domain)

            explicit_domains = {
                str(item.get("domain_hint"))
                for item in constraints.explicit_activities
                if item.get("modality") == "required" and item.get("domain_hint")
            }
            required_domains: set[IntentDomain] = set()
            normalized_slots: list[ActivitySlot] = []
            for slot in semantic_slots:
                if slot.role == "optional":
                    normalized_slots.append(
                        slot.model_copy(update={"required": False, "source": "inferred"})
                    )
                    continue
                required = (
                    slot.domain is not None
                    and slot.domain.value in explicit_domains
                    and slot.domain not in required_domains
                )
                if required and slot.domain is not None:
                    required_domains.add(slot.domain)
                normalized_slots.append(
                    slot.model_copy(
                        update={
                            "required": required,
                            "source": "explicit" if required else "inferred",
                            "requirement_level": "hard" if required else "optional",
                            "order_policy": "fixed" if required else "flexible",
                        }
                    )
                )
            semantic_slots = normalized_slots
            if constraints.time_expression_kind == "full_day":
                density_target = max(3, min(5, int(constraints.poi_count_target or 4)))
                existing_ids = {slot.slot_id for slot in semantic_slots}
                anchor_count = sum(slot.role == "anchor" for slot in semantic_slots)
                for supplement in fallback[style].slots:
                    if anchor_count >= density_target:
                        break
                    if supplement.role != "anchor" or supplement.slot_id in existing_ids:
                        continue
                    semantic_slots.append(
                        supplement.model_copy(
                            update={
                                "required": False,
                                "source": "inferred",
                                "requirement_level": "optional",
                                "order_policy": "flexible",
                            }
                        )
                    )
                    existing_ids.add(supplement.slot_id)
                    anchor_count += 1
        if constraints.anchor_count_explicit:
            kept = 0
            capped: list[ActivitySlot] = []
            for slot in semantic_slots:
                if slot.role == "anchor":
                    if kept >= constraints.anchor_count_explicit:
                        continue
                    kept += 1
                    slot = slot.model_copy(update={"required": True, "source": "explicit"})
                else:
                    slot = slot.model_copy(update={"required": False, "source": "inferred"})
                capped.append(slot)
            semantic_slots = capped
        sanitized = draft.model_copy(
            update={
                "blueprint_id": f"bp-{style}",
                "scene_type": _scene_type(constraints),
                "slots": semantic_slots,
            }
        )
        normalized.append(apply_slot_policy(sanitized, constraints))
    return normalized


async def generate_blueprints_with_meta(
    state: GraphState,
) -> tuple[list[ItineraryBlueprint], dict]:
    constraints = Constraints.model_validate(state.get("constraints") or {})
    mode = settings.activity_blueprint_mode
    blueprint_count = max(1, min(settings.activity_blueprint_count, 2))
    if mode == "rule_only" or not settings.llm_enabled:
        return build_rule_blueprints(constraints)[:blueprint_count], {
            "operation": "activity_blueprint",
            "status": "skipped",
            "source": "rule_fallback",
        }
    if not settings.llm_api_key:
        if mode == "llm_only":
            raise LLMError("LLM API key not configured")
        return build_rule_blueprints(constraints)[:blueprint_count], {
            "operation": "activity_blueprint",
            "status": "skipped",
            "fallback_used": True,
            "source": "rule_fallback",
        }
    try:
        start, end = _window(constraints)
        drafts, meta = await generate_blueprint_drafts_with_meta(
            constraints,
            start_at=_hhmm(start),
            return_by=_hhmm(end),
            scene_type=_scene_type(constraints),
        )
        return normalize_llm_blueprints(drafts, constraints)[
            :blueprint_count
        ], meta
    except (LLMError, ValidationError) as exc:
        if mode == "llm_only":
            raise
        return build_rule_blueprints(constraints)[:blueprint_count], failure_meta("activity_blueprint", exc)
