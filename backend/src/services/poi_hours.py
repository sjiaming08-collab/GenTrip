"""Opening-hour parsing shared by POI tools and route validation."""

from __future__ import annotations

from datetime import datetime
from typing import Any


_WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def parse_hhmm(value: object) -> int | None:
    if not isinstance(value, str) or ":" not in value:
        return None
    hour_text, minute_text = value.split(":", 1)
    if not (hour_text.isdigit() and minute_text.isdigit()):
        return None
    hour = int(hour_text)
    minute = int(minute_text)
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return hour * 60 + minute


def opening_intervals(opening_hours: object) -> list[tuple[int, int]]:
    if not isinstance(opening_hours, list):
        return []
    intervals: list[tuple[int, int]] = []
    for item in opening_hours:
        if not isinstance(item, dict):
            continue
        start = parse_hhmm(item.get("open"))
        end = parse_hhmm(item.get("close"))
        if start is None or end is None or start == end:
            continue
        if end < start:
            end += 24 * 60
        intervals.append((start, end))
    return intervals


def weekday_from_date(value: object) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).weekday()
    except ValueError:
        return None


def _matches_day(value: object, weekday: int | None) -> bool:
    if weekday is None or not isinstance(value, str) or not value:
        return True
    for token in value.lower().replace(" ", "").split(","):
        if "-" in token:
            start, end = token.split("-", 1)
            if start[:3] not in _WEEKDAYS or end[:3] not in _WEEKDAYS:
                continue
            first, last = _WEEKDAYS[start[:3]], _WEEKDAYS[end[:3]]
            if (first <= last and first <= weekday <= last) or (first > last and (weekday >= first or weekday <= last)):
                return True
        elif token[:3] in _WEEKDAYS and _WEEKDAYS[token[:3]] == weekday:
            return True
    return False


def is_open_during(
    opening_hours: object,
    arrival_minute: int,
    departure_minute: int,
    *,
    weekday: int | None = None,
) -> bool | None:
    """Return None when fixture data has no usable hours, otherwise availability."""
    intervals = opening_intervals(opening_hours)
    if not intervals:
        return None
    start = arrival_minute % (24 * 60)
    end = departure_minute % (24 * 60)
    if departure_minute - arrival_minute >= 24 * 60:
        return False
    if end < start:
        end += 24 * 60
    for item in opening_hours if isinstance(opening_hours, list) else []:
        if not isinstance(item, dict) or not _matches_day(item.get("days"), weekday):
            continue
        open_minute = parse_hhmm(item.get("open"))
        close_minute = parse_hhmm(item.get("close"))
        if open_minute is None or close_minute is None or open_minute == close_minute:
            continue
        if close_minute < open_minute:
            close_minute += 24 * 60
        for offset in (0, 24 * 60):
            if start >= open_minute + offset and end <= close_minute + offset:
                return True
    return False


def next_opening_start(
    opening_hours: object,
    earliest_minute: int,
    required_duration_min: int,
    *,
    weekday: int | None = None,
) -> int | None:
    """Return the earliest same-day start that can fit the requested visit."""
    if not isinstance(opening_hours, list) or not opening_intervals(opening_hours):
        return earliest_minute
    candidates: list[int] = []
    for item in opening_hours:
        if not isinstance(item, dict) or not _matches_day(item.get("days"), weekday):
            continue
        open_minute = parse_hhmm(item.get("open"))
        close_minute = parse_hhmm(item.get("close"))
        if open_minute is None or close_minute is None or open_minute == close_minute:
            continue
        if close_minute < open_minute:
            close_minute += 24 * 60
        start = max(earliest_minute, open_minute)
        if start + max(0, required_duration_min) <= close_minute:
            candidates.append(start)
    return min(candidates) if candidates else None
