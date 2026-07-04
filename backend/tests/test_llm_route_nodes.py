import pytest

from src.config import settings
from src.llm.route_evaluate import llm_score_routes
from src.llm.route_present import llm_present_route
from src.models.route import RoutePlan, RoutePlanResult, RouteScores, RouteSource, RouteStop


class FakeClient:
    def __init__(self, payload):
        self.payload = payload

    async def chat_json(self, system, user):
        return self.payload


def _route(plan_id="r1"):
    return RoutePlan(
        plan_id=plan_id,
        plan_name="徐汇文艺逛吃",
        summary="咖啡、看展、正餐",
        total_duration_min=150,
        estimated_cost_per_person=120,
        stops=[
            RouteStop(
                sequence=1,
                poi_id="p1",
                poi_name="安福路咖啡",
                category="咖啡",
                arrival_time="10:00",
                departure_time="11:00",
                visit_duration_min=60,
            )
        ],
    )


@pytest.mark.asyncio
async def test_llm_score_routes_uses_structured_scores(monkeypatch):
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(
        "src.llm.route_evaluate.get_llm_client",
        lambda: FakeClient({
            "scores": [
                {"plan_id": "r1", "execution": 0.9, "quality": 0.85, "preference": 0.8, "comment": "节奏合理"}
            ]
        }),
    )

    scores = await llm_score_routes([_route()], constraints={}, user_query="徐汇逛吃")

    assert scores["r1"].execution == 0.9
    assert scores["r1"].comment == "节奏合理"


@pytest.mark.asyncio
async def test_llm_present_route_enforces_recommend_prefix(monkeypatch):
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(
        "src.llm.route_present.get_llm_client",
        lambda: FakeClient({
            "title": "徐汇半日文艺漫步",
            "summary": "从咖啡开始，再去看展。",
            "highlights": ["3站", "人均120元"],
        }),
    )
    result = RoutePlanResult(
        route=_route(),
        source=RouteSource.COLD_GENERATED,
        rank=1,
        scores=RouteScores(execution=0.9, quality=0.85, final=0.86),
    )

    presentation = await llm_present_route([result], user_query="徐汇逛吃", assumptions=[], relaxed_constraints=[])

    assert presentation is not None
    assert presentation.title.startswith("为您推荐")
    assert presentation.highlights == ["3站", "人均120元"]
