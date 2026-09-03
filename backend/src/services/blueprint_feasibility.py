"""POI-free temporal feasibility compiler for semantic blueprints."""

from __future__ import annotations

from copy import deepcopy

from ..models.blueprint import ActivitySlot, ItineraryBlueprint, SlotTimeWindow
from ..models.constraints import CompiledConstraints, Constraints


def _minute(value: str | None, default: int) -> int:
    if not value:
        return default
    hour, minute = value.split(":", 1)
    return int(hour) * 60 + int(minute)


def _hhmm(value: int) -> str:
    value = max(0, min(value, 23 * 60 + 59))
    return f"{value // 60:02d}:{value % 60:02d}"


def _duration(slot: ActivitySlot, mode: str) -> int:
    if mode == "optimistic":
        return int(slot.duration_min_minutes or max(15, slot.duration_minutes - 30))
    if mode == "conservative":
        return int(slot.duration_max_minutes or min(240, slot.duration_minutes + 30))
    return int(slot.duration_minutes)


def _transfer(slot: ActivitySlot, mode: str, *, first: bool) -> int:
    if first or slot.role == "rest":
        return 0
    if slot.spatial_policy == "near_anchor":
        return {"optimistic": 10, "expected": 20, "conservative": 40}[mode]
    return {"optimistic": 5, "expected": 15, "conservative": 30}[mode]


def _schedule(
    slots: list[ActivitySlot],
    *,
    start: int,
    end: int,
    mode: str,
    hard_end: bool,
) -> tuple[bool, list[dict], dict | None]:
    cursor = start
    timeline: list[dict] = []
    for index, slot in enumerate(slots):
        cursor += _transfer(slot, mode, first=index == 0)
        window_start = _minute(slot.time_window.start, cursor) if slot.time_window else None
        window_end = _minute(slot.time_window.end, end) if slot.time_window else None
        if window_start is not None:
            cursor = max(cursor, window_start)
        finish = cursor + _duration(slot, mode)
        if (
            window_end is not None
            and finish > window_end
            and slot.requirement_level in {"hard", "policy"}
        ):
            return False, timeline, {
                "failure_type": "temporal_conflict",
                "slot_id": slot.slot_id,
                "earliest_possible_time": _hhmm(cursor),
                "latest_allowed_time": _hhmm(window_end - _duration(slot, mode)),
                "blocking_constraints": ["slot_time_window"],
            }
        if hard_end and finish > end:
            return False, timeline, {
                "failure_type": "temporal_conflict",
                "slot_id": slot.slot_id,
                "earliest_possible_time": _hhmm(cursor),
                "latest_allowed_time": _hhmm(end - _duration(slot, mode)),
                "blocking_constraints": ["schedule_end"],
            }
        timeline.append({
            "slot_id": slot.slot_id,
            "start": _hhmm(cursor),
            "end": _hhmm(finish),
            "duration_minutes": _duration(slot, mode),
        })
        cursor = finish
    return True, timeline, None


def _normalize_levels(slots: list[ActivitySlot], constraints: Constraints) -> list[ActivitySlot]:
    explicit_domains = {
        str(item.get("domain_hint"))
        for item in constraints.explicit_activities
        if item.get("modality") == "required" and item.get("domain_hint")
    }
    claimed_domains: set[str] = set()
    normalized: list[ActivitySlot] = []
    hard_remaining = int(constraints.anchor_count_explicit or 0)
    for slot in slots:
        if slot.role == "rest":
            level = "policy"
        elif slot.role == "meal" and slot.source == "policy":
            level = "policy"
        elif slot.role == "optional":
            level = "optional"
        elif hard_remaining > 0:
            level = "hard"
            hard_remaining -= 1
        elif slot.domain and slot.domain.value in explicit_domains and slot.domain.value not in claimed_domains:
            level = "hard"
            claimed_domains.add(slot.domain.value)
        else:
            level = "optional"
        normalized.append(slot.model_copy(update={
            "requirement_level": level,
            "required": level == "hard",
            "source": "explicit" if level == "hard" else ("policy" if level == "policy" else "inferred"),
            "order_policy": "fixed" if level == "hard" else "flexible",
            "duration_min_minutes": slot.duration_min_minutes or max(15, slot.duration_minutes - 30),
            "duration_max_minutes": slot.duration_max_minutes or min(240, slot.duration_minutes + 30),
        }))
    return normalized


def _repair_expected_schedule(
    slots: list[ActivitySlot],
    *,
    start: int,
    end: int,
    hard_end: bool,
) -> tuple[list[ActivitySlot], list[dict]]:
    repaired = list(slots)
    actions: list[dict] = []
    while True:
        feasible, _timeline, conflict = _schedule(
            repaired, start=start, end=end, mode="expected", hard_end=hard_end
        )
        if feasible:
            return repaired, actions
        conflict_index = next(
            (index for index, slot in enumerate(repaired) if slot.slot_id == (conflict or {}).get("slot_id")),
            len(repaired) - 1,
        )
        conflicting_slot = repaired[conflict_index]
        if conflicting_slot.requirement_level == "optional":
            removed = repaired.pop(conflict_index)
            actions.append({"action": "drop_optional", "slot_id": removed.slot_id})
            continue
        optional_index = next(
            (
                index for index in range(conflict_index - 1, -1, -1)
                if repaired[index].requirement_level == "optional"
            ),
            None,
        )
        if optional_index is not None:
            moved = repaired.pop(optional_index)
            conflict_index -= 1 if optional_index < conflict_index else 0
            if conflicting_slot.requirement_level == "policy":
                repaired.insert(conflict_index + 1, moved)
                actions.append({
                    "action": "move_optional_after_policy",
                    "slot_id": moved.slot_id,
                    "policy_slot_id": conflicting_slot.slot_id,
                })
            else:
                actions.append({"action": "drop_optional", "slot_id": moved.slot_id})
            continue
        policy_index = next(
            (
                index for index in range(conflict_index, -1, -1)
                if repaired[index].requirement_level == "policy"
            ),
            None,
        )
        if policy_index is not None:
            removed = repaired.pop(policy_index)
            actions.append({"action": "drop_policy", "slot_id": removed.slot_id})
            continue
        return repaired, actions


def compile_blueprint_feasibility(
    blueprint: ItineraryBlueprint,
    constraints: Constraints,
    compiled: CompiledConstraints,
) -> tuple[ItineraryBlueprint | None, dict]:
    """Compile one draft and report structural feasibility before POI search."""

    envelope = compiled.schedule_envelope
    start = _minute(blueprint.start_at, _minute(envelope.earliest_start, 10 * 60))
    if envelope.earliest_start:
        start = max(start, _minute(envelope.earliest_start, start))
    envelope_end = _minute(
        envelope.latest_end,
        start + envelope.max_duration_minutes,
    )
    end = min(envelope_end, start + envelope.max_duration_minutes)
    slots = _normalize_levels([deepcopy(slot) for slot in blueprint.slots], constraints)
    slots, repair_actions = _repair_expected_schedule(
        slots, start=start, end=end, hard_end=True
    )

    optimistic_ok, optimistic_timeline, optimistic_conflict = _schedule(
        slots, start=start, end=end, mode="optimistic", hard_end=True
    )
    expected_ok, expected_timeline, expected_conflict = _schedule(
        slots, start=start, end=end, mode="expected", hard_end=True
    )
    conservative_ok, conservative_timeline, _ = _schedule(
        slots, start=start, end=end, mode="conservative", hard_end=True
    )
    hard_slots = [slot for slot in slots if slot.requirement_level == "hard"]
    if not optimistic_ok and hard_slots:
        return None, {
            "blueprint_id": blueprint.blueprint_id,
            "status": "infeasible",
            "conflicts": [optimistic_conflict] if optimistic_conflict else [],
            "repair_actions": repair_actions,
            "slot_time_envelopes": [],
        }

    status = "feasible" if expected_ok and conservative_ok else "feasible_with_risk"
    chosen_timeline = expected_timeline if expected_ok else optimistic_timeline
    by_slot = {item["slot_id"]: item for item in chosen_timeline}
    compiled_slots = [
        slot.model_copy(update={
            "duration_minutes": by_slot.get(slot.slot_id, {}).get("duration_minutes", slot.duration_minutes),
            "expected_time_window": (
                SlotTimeWindow(
                    start=by_slot[slot.slot_id]["start"],
                    end=by_slot[slot.slot_id]["end"],
                ) if slot.slot_id in by_slot else None
            ),
        })
        for slot in slots
    ]
    result = blueprint.model_copy(update={
        "start_at": _hhmm(start),
        "return_by": _hhmm(end),
        "slots": compiled_slots,
    })
    return result, {
        "blueprint_id": blueprint.blueprint_id,
        "status": status,
        "optimistic_duration_minutes": (
            _minute(optimistic_timeline[-1]["end"], start) - start if optimistic_timeline else 0
        ),
        "expected_duration_minutes": (
            _minute(chosen_timeline[-1]["end"], start) - start if chosen_timeline else 0
        ),
        "conservative_duration_minutes": (
            _minute(conservative_timeline[-1]["end"], start) - start
            if conservative_ok and conservative_timeline
            else None
        ),
        "slot_time_envelopes": chosen_timeline,
        "conflicts": [expected_conflict] if expected_conflict else [],
        "repair_actions": repair_actions,
    }
