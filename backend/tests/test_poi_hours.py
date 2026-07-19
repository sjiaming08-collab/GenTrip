from src.services.poi_hours import is_open_during, weekday_from_date


def test_weekday_specific_opening_hours():
    hours = [
        {"days": "Mon-Fri", "open": "09:00", "close": "18:00"},
        {"days": "Sat-Sun", "open": "11:00", "close": "16:00"},
    ]

    assert weekday_from_date("2026-07-20") == 0  # Monday
    assert is_open_during(hours, 10 * 60, 11 * 60, weekday=0) is True
    assert is_open_during(hours, 10 * 60, 11 * 60, weekday=5) is False
    assert is_open_during(hours, 12 * 60, 13 * 60, weekday=5) is True
