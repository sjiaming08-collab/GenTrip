"""Compile normalized query facts into hard, soft, and policy constraints."""

from __future__ import annotations

import re

from ..models.constraints import (
    CompiledConstraints,
    ConstraintAtom,
    Constraints,
    ConstraintStrength,
    ScheduleEnvelope,
)
from .constraint_rules import (
    derive_time_budget_minutes,
    detect_full_day_expression,
    detect_minutes,
)


_DAYPART_RE = re.compile(r"上午|早上|中午|下午|午后|晚上|夜间")
_AROUND_RE = re.compile(r"左右|大概|大约|差不多|约")
_MAX_RE = re.compile(r"最多|不超过|以内|上限")
_NO_MEAL_RE = re.compile(r"(?:不吃饭|不要吃饭|不安排餐|不需要用餐|不吃午餐|不吃晚餐)")
_EXPLICIT_ACTIVITY_SIGNALS = {
    "dining": ("吃", "餐", "饭", "美食", "料理", "咖啡", "下午茶", "甜品"),
    "shopping": ("购物", "逛街", "商场", "百货", "书店", "买手店", "买东西"),
    "leisure": ("按摩", "足疗", "SPA", "健身", "电玩", "桌游", "密室", "KTV", "演出", "亲子"),
    "sightseeing": ("观光", "打卡", "看展", "博物馆", "美术馆", "公园", "景点", "散步", "步道"),
}


def _atom(
    constraint_id: str,
    field: str,
    value,
    strength: ConstraintStrength,
    source: str,
    *,
    evidence: str | None = None,
    priority: int,
    operator: str = "equals",
    overridable: bool | None = None,
    relax_policy: str | None = None,
) -> ConstraintAtom:
    return ConstraintAtom(
        constraint_id=constraint_id,
        field=field,
        operator=operator,
        value=value,
        strength=strength,
        source=source,
        evidence=evidence,
        priority=priority,
        overridable=(strength != ConstraintStrength.HARD if overridable is None else overridable),
        relax_policy=relax_policy,
    )


def _schedule_envelope(constraints: Constraints) -> ScheduleEnvelope:
    query = constraints.raw_query
    clock_minutes = derive_time_budget_minutes(constraints.start_at, constraints.return_by)
    if clock_minutes is not None:
        return ScheduleEnvelope(
            time_scope="clock_window",
            earliest_start=constraints.start_at,
            latest_end=constraints.return_by,
            min_duration_minutes=clock_minutes,
            target_duration_minutes=clock_minutes,
            max_duration_minutes=clock_minutes,
            flexibility="hard",
            source="derived",
        )

    if detect_full_day_expression(query):
        return ScheduleEnvelope(
            time_scope="full_day",
            earliest_start="09:30",
            latest_end="20:30",
            min_duration_minutes=420,
            target_duration_minutes=540,
            max_duration_minutes=600,
            flexibility="soft",
            source="policy",
        )

    explicit_minutes = detect_minutes(query)
    if explicit_minutes is not None:
        qualifier_around = bool(_AROUND_RE.search(query))
        spread = 30 if qualifier_around else 0
        return ScheduleEnvelope(
            time_scope="exact_duration",
            earliest_start=constraints.start_at,
            latest_end=constraints.return_by,
            min_duration_minutes=max(30, explicit_minutes - spread),
            target_duration_minutes=explicit_minutes,
            max_duration_minutes=explicit_minutes + spread,
            flexibility="soft" if qualifier_around else "hard",
            source="user",
        )

    if _DAYPART_RE.search(query):
        if re.search(r"下午|午后", query):
            start, end = "13:30", "18:00"
        elif re.search(r"晚上|夜间", query):
            start, end = "18:00", "22:00"
        elif "中午" in query:
            start, end = "11:30", "14:00"
        else:
            start, end = "09:00", "12:00"
        duration = derive_time_budget_minutes(start, end) or 180
        return ScheduleEnvelope(
            time_scope="daypart",
            earliest_start=start,
            latest_end=end,
            min_duration_minutes=max(60, duration - 60),
            target_duration_minutes=duration,
            max_duration_minutes=duration,
            flexibility="soft",
            source="policy",
        )

    target = int(constraints.time_budget_minutes or 180)
    return ScheduleEnvelope(
        time_scope="unspecified",
        earliest_start=constraints.start_at,
        latest_end=constraints.return_by,
        min_duration_minutes=max(60, min(120, target)),
        target_duration_minutes=target,
        max_duration_minutes=max(240, target),
        flexibility="soft",
        source="default",
    )


def compile_constraints(constraints: Constraints) -> tuple[Constraints, CompiledConstraints]:
    """Return the backward-compatible constraints plus the V3 compiled view."""

    query = constraints.raw_query
    envelope = _schedule_envelope(constraints)
    atoms: list[ConstraintAtom] = []
    active_policies: list[dict] = []
    dropped_policies: list[dict] = []

    for index, location in enumerate(constraints.location_mentions):
        atoms.append(_atom(
            f"geo-anchor-{index + 1}", "geo_anchor", location,
            ConstraintStrength.HARD, "user", evidence=location, priority=100,
        ))
    if constraints.geo_relation == "nearby" or "附近" in query or "周边" in query:
        atoms.append(_atom(
            "geo-nearby", "geo_relation", "nearby", ConstraintStrength.SOFT,
            "user", evidence="附近" if "附近" in query else "周边", priority=85,
            relax_policy="expand_named_area_radius",
        ))

    time_strength = (
        ConstraintStrength.HARD
        if envelope.flexibility == "hard" or envelope.time_scope == "full_day"
        else ConstraintStrength.POLICY
    )
    atoms.append(_atom(
        "time-scope", "time_scope", envelope.time_scope, time_strength,
        "user" if time_strength == ConstraintStrength.HARD else "default",
        evidence=(detect_full_day_expression(query) if envelope.time_scope == "full_day" else None),
        priority=95 if time_strength == ConstraintStrength.HARD else 45,
    ))
    if envelope.flexibility == "soft":
        atoms.append(_atom(
            "time-target", "target_duration_minutes", envelope.target_duration_minutes,
            ConstraintStrength.POLICY, "derived", priority=45,
            relax_policy="stay_within_schedule_envelope",
        ))

    for domain in constraints.domains:
        atoms.append(_atom(
            f"search-domain-{domain.value}", "search_domain", domain.value,
            ConstraintStrength.SOFT, "derived", priority=55,
        ))

    explicit_activities = list(constraints.explicit_activities)
    if not explicit_activities:
        for domain in constraints.domains:
            signal = next(
                (term for term in _EXPLICIT_ACTIVITY_SIGNALS[domain.value] if term in query),
                None,
            )
            if signal:
                explicit_activities.append({
                    "text": signal,
                    "domain_hint": domain.value,
                    "categories": [],
                    "modality": "required",
                    "evidence": signal,
                })

    for index, activity in enumerate(explicit_activities):
        modality = str(activity.get("modality") or "required")
        strength = ConstraintStrength.HARD if modality in {"required", "prohibited"} else ConstraintStrength.SOFT
        atoms.append(_atom(
            f"activity-{index + 1}", "activity", activity,
            strength, "user", evidence=activity.get("evidence"),
            priority=100 if strength == ConstraintStrength.HARD else 75,
            operator="not_contains" if modality == "prohibited" else "contains",
        ))

    for index, excluded in enumerate(constraints.excluded_categories):
        atoms.append(_atom(
            f"exclusion-{index + 1}", "excluded_category", excluded,
            ConstraintStrength.HARD, "user", evidence=excluded, priority=100,
            operator="not_contains",
        ))

    if constraints.anchor_count_explicit:
        atoms.append(_atom(
            "anchor-count", "anchor_count", constraints.anchor_count_explicit,
            ConstraintStrength.HARD, "user", priority=100,
        ))

    budget_strength = ConstraintStrength.HARD if _MAX_RE.search(query) else ConstraintStrength.POLICY
    atoms.append(_atom(
        "budget", "budget_per_person", constraints.budget_per_person,
        budget_strength, "user" if budget_strength == ConstraintStrength.HARD else "default",
        priority=90 if budget_strength == ConstraintStrength.HARD else 35,
        operator="less_than_or_equal" if budget_strength == ConstraintStrength.HARD else "target",
    ))

    if _NO_MEAL_RE.search(query):
        dropped_policies.append({"policy_id": "meal-service", "reason": "explicit_no_meal"})
    elif envelope.max_duration_minutes >= 300:
        active_policies.append({
            "policy_id": "meal-lunch", "status": "proposed", "priority": 70,
            "window": {"start": "11:30", "end": "13:30"},
        })
        latest_end_minutes = None
        if envelope.latest_end:
            hour, minute = envelope.latest_end.split(":", 1)
            latest_end_minutes = int(hour) * 60 + int(minute)
        if envelope.time_scope == "full_day" or (
            latest_end_minutes is not None and latest_end_minutes >= 18 * 60 + 30
        ):
            active_policies.append({
                "policy_id": "meal-dinner", "status": "proposed", "priority": 65,
                "window": {"start": "17:30", "end": "19:30"},
            })
    active_policies.append({
        "policy_id": "activity-density", "status": "active", "priority": 40,
        "target_range": [3, 5] if envelope.time_scope == "full_day" else [1, 3],
    })

    if envelope.time_scope == "full_day":
        legacy_minutes = envelope.max_duration_minutes
        legacy_target = constraints.anchor_count_explicit or 4
    else:
        legacy_minutes = envelope.target_duration_minutes
        legacy_target = constraints.poi_count

    compiled_constraints = constraints.model_copy(update={
        "time_budget_minutes": legacy_minutes,
        "time_expression_kind": envelope.time_scope,
        "time_budget_hard": envelope.flexibility == "hard",
        "schedule_envelope": envelope,
        "poi_count": legacy_target,
        "poi_count_target": legacy_target,
        "poi_count_min": legacy_target if constraints.anchor_count_explicit else max(1, legacy_target - 1),
        "poi_count_max": min(8, legacy_target if constraints.anchor_count_explicit else legacy_target + 2),
        "geo_relation": constraints.geo_relation or ("nearby" if "附近" in query or "周边" in query else None),
        "explicit_activities": explicit_activities,
    })
    compiled = CompiledConstraints(
        atoms=atoms,
        schedule_envelope=envelope,
        search_domains=constraints.domains,
        active_policies=active_policies,
        dropped_policies=dropped_policies,
    )
    return compiled_constraints, compiled
