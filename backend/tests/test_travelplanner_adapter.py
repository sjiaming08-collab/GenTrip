import json
from pathlib import Path

from src.evaluation.travelplanner import (
    adapt_record,
    build_derived_cases,
    build_travelplanner_report,
    constraint_check,
)


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "travelplanner_gentrip_validation.json"
POI_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "travelplanner_pois.json"


def _record(*, level: str = "hard", days: str = "5") -> dict[str, str]:
    return {
        "org": "Boston",
        "dest": "Chicago",
        "days": days,
        "people_number": "2",
        "budget": "1800",
        "level": level,
        "query": "Plan a trip from Boston to Chicago.",
        "local_constraint": (
            "{'house rule': 'smoking', 'cuisine': ['Chinese', 'Italian'], "
            "'room type': None, 'transportation': 'no flight'}"
        ),
    }


def test_adapter_is_deterministic_and_declares_non_official_scope():
    first = adapt_record(_record(), source_index=4, split="validation")
    second = adapt_record(_record(), source_index=4, split="validation")

    assert first == second
    assert first["adaptation"]["official_travelplanner_score"] is False
    assert first["adaptation"]["mapping"]["preferred_cuisines"] == ["本帮菜", "西餐"]
    assert "accommodation_house_rule" in first["adaptation"]["unsupported_dimensions"]
    assert "intercity_transport_preference" in first["adaptation"]["unsupported_dimensions"]
    assert "包含观光和吃饭" in first["query"]
    assert first["expect"]["min_stops"] == 3
    assert first["expect"]["required_category_groups"] == [["本帮菜", "西餐"]]


def test_balanced_builder_selects_each_level_and_day_cell():
    records = [
        _record(level=level, days=str(days))
        for level in ("easy", "medium", "hard")
        for days in (3, 5, 7)
        for _ in range(2)
    ]

    cases = build_derived_cases(records, split="validation", samples_per_cell=1)

    assert len(cases) == 9
    assert {(case["source"]["level"], case["source"]["days"]) for case in cases} == {
        (level, days) for level in ("easy", "medium", "hard") for days in (3, 5, 7)
    }


def test_constraint_check_and_report_keep_official_score_empty():
    case = adapt_record(_record(), source_index=1, split="validation")
    expected = case["expect"]["expected_constraints"]
    result = {
        "id": case["id"],
        "passed": True,
        "is_completed": True,
        "is_legal": True,
        "quality_score": 0.8,
        "constraints": expected,
        "runtime": {"latency_ms": 1200, "token_usage": {"total_tokens": 321}},
    }

    assert constraint_check(case, result)["score"] == 1.0
    report = build_travelplanner_report([case], [result], live_llm=True)
    assert report["official_travelplanner_score"] is None
    assert report["summary"]["route_case_pass_rate"] == 1.0
    assert report["summary"]["end_to_end_pass_rate"] == 1.0
    assert report["summary"]["constraint_micro_pass_rate"] == 1.0
    assert report["summary"]["total_tokens"] == 321


def test_committed_validation_fixture_is_balanced_and_non_official():
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert len(cases) == 18
    assert all(case["adaptation"]["official_travelplanner_score"] is False for case in cases)
    assert {
        (case["source"]["level"], case["source"]["days"])
        for case in cases
    } == {(level, days) for level in ("easy", "medium", "hard") for days in (3, 5, 7)}


def test_committed_poi_fixture_is_isolated_and_covers_every_case():
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
    fixture = json.loads(POI_FIXTURE.read_text(encoding="utf-8"))
    pois = fixture["pois"]

    assert fixture["metadata"]["evaluation_only"] is True
    assert fixture["metadata"]["poi_count"] == len(pois) == 324
    assert {poi["district"] for poi in pois} == {"黄浦区", "徐汇区", "静安区", "浦东新区"}
    assert all(poi["data_tier"] == "benchmark_derived" for poi in pois)
    for case in cases:
        case_tag = f"case:{case['id']}"
        case_pois = [poi for poi in pois if case_tag in poi["tags"]]
        assert len(case_pois) == 18
        assert {poi["category"] for poi in case_pois} == {"景点", "美食"}
