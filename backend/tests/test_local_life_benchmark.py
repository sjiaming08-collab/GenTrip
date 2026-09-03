import json
from pathlib import Path

import pytest

from src.evaluation.local_life import (
    AGENTS,
    DIFFICULTIES,
    DISTRICTS,
    build_dataset,
    poi_coverage_issues,
)
from src.models.constraints import IntentDomain
from src.services.category_taxonomy import domain_for_category
from src.services.constraint_rules import detect_excluded_categories
from src.services.poi_retrieval import _GeoRelaxStep, _matches_geo


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DATASET_PATH = FIXTURES / "local_life_benchmark.json"
POI_PATH = FIXTURES / "pois.json"


def test_local_life_fixture_is_balanced_and_versioned():
    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    cases = dataset["cases"]

    assert dataset["metadata"]["version"] == "local-life-v1-20260817"
    assert dataset["metadata"]["official_travelplanner_score"] is False
    assert len(dataset["agents"]) == len(AGENTS) == 10
    assert len(cases) == len(AGENTS) * len(DISTRICTS) * len(DIFFICULTIES) == 120
    assert len(dataset["conversations"]) == 10
    assert sum(len(item["turns"]) for item in dataset["conversations"]) == 30
    assert dataset["metadata"]["quality_gate"] == {
        "minimum_constraint_pass_rate": 0.98,
        "minimum_single_end_to_end_pass_rate": 0.90,
        "minimum_mean_quality_score": 0.90,
        "minimum_conversation_turn_pass_rate": 0.95,
    }
    assert {
        (case["agent_id"], case["difficulty"], case["expect"]["expected_constraints"]["district"])
        for case in cases
    } == {
        (agent.id, difficulty, district)
        for agent in AGENTS
        for difficulty in DIFFICULTIES
        for district in DISTRICTS
    }


def test_committed_fixture_matches_deterministic_builder():
    committed = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    assert committed == build_dataset()


def test_all_scenarios_have_native_poi_coverage():
    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    pois = json.loads(POI_PATH.read_text(encoding="utf-8"))
    assert poi_coverage_issues(dataset, pois) == []


@pytest.mark.parametrize(
    ("category", "domain"),
    [
        ("日料", IntentDomain.DINING),
        ("正餐", IntentDomain.DINING),
        ("公园", IntentDomain.SIGHTSEEING),
        ("商场", IntentDomain.SHOPPING),
        ("按摩", IntentDomain.LEISURE),
        ("羽毛球", IntentDomain.LEISURE),
        ("儿童乐园", IntentDomain.LEISURE),
    ],
)
def test_category_domain_resolution_supports_cross_domain_replan(category, domain):
    assert domain_for_category(category) == domain


def test_hard_case_dining_negation_is_not_a_positive_preference():
    assert detect_excluded_categories("不吃火锅，想吃本帮菜") == ["火锅"]


def test_geo_match_requires_radius_and_explicit_district():
    geo = _GeoRelaxStep(
        "G0",
        district="黄浦区",
        center_lat=31.2304,
        center_lng=121.4737,
        radius_m=5000,
    )
    nearby_wrong_district = {
        "district": "静安区",
        "location": {"lat": 31.2310, "lng": 121.4740},
    }
    assert not _matches_geo(nearby_wrong_district, geo)
