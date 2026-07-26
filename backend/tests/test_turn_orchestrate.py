import pytest

from src.graph.nodes import turn_orchestrate as turn_orchestrate_module
from src.graph.nodes.turn_orchestrate import turn_orchestrate
from src.graph.nodes.reject_reply import reject_reply
from src.graph.state import build_initial_state
from src.llm.turn_classify import LlmReplanOp, LlmTurnDecision


@pytest.mark.asyncio
async def test_turn_orchestrate_rejects_non_travel_query():
    state = build_initial_state("今天股票怎么样")
    update = await turn_orchestrate(state)

    assert update["turn_mode"] == "reject"
    assert update["route_intent"]["intent_type"] == "non_travel"


@pytest.mark.asyncio
async def test_turn_orchestrate_detects_replan_with_current_route():
    state = build_initial_state("不要这家店，换一家咖啡")
    state["session_current_route"] = {"plan_id": "old"}
    update = await turn_orchestrate(state)

    assert update["turn_mode"] == "replan"
    assert update["run_mode"] == "replan"
    assert update["route_intent"]["intent_type"] == "revision"


@pytest.mark.asyncio
async def test_turn_orchestrate_generic_food_followup_is_replan_without_llm():
    state = build_initial_state("我还想去吃东西呢")
    state["session_current_route"] = {"plan_id": "old", "stops": [{"poi_name": "公园"}]}

    update = await turn_orchestrate(state)

    assert update["turn_mode"] == "replan"
    assert update["run_mode"] == "replan"


@pytest.mark.asyncio
async def test_turn_orchestrate_prefers_llm_intent_adjustment_over_keyword_fallback(monkeypatch):
    async def llm_adjustment(*_args, **_kwargs):
        return (
            LlmTurnDecision(
                turn_mode="replan",
                primary_intent="亲子",
                query_understanding="用户想微调当前路线",
                replan_operation=LlmReplanOp(type="replace", target_seq=2, new_cuisine="咖啡"),
            ),
            {"operation": "turn_classify", "status": "success", "model": "test-model"},
        )

    monkeypatch.setattr(turn_orchestrate_module, "classify_turn", llm_adjustment)
    state = build_initial_state("换个更轻松的安排")
    state["session_current_route"] = {"plan_id": "old", "stops": [{"poi_name": "旧地点"}]}

    update = await turn_orchestrate(state)

    assert update["turn_mode"] == "replan"
    assert update["route_intent"]["primary_intent"] == "亲子"
    assert update["replan_operation"] == {
        "type": "replace",
        "target_seq": 2,
        "target_category": None,
        "new_cuisine": "咖啡",
        "after_seq": None,
        "overrides": {},
    }
    assert update["llm_calls"][0]["status"] == "success"


@pytest.mark.asyncio
async def test_turn_orchestrate_rejects_llm_replan_for_a_fresh_request(monkeypatch):
    async def llm_false_replan(*_args, **_kwargs):
        return (
            LlmTurnDecision(turn_mode="replan", replan_operation=LlmReplanOp(type="add", new_cuisine="日料")),
            {"operation": "turn_classify", "status": "success", "model": "test-model"},
        )

    monkeypatch.setattr(turn_orchestrate_module, "classify_turn", llm_false_replan)
    state = build_initial_state("适合朋友聚会，黄浦区，人均100元，3小时")
    state["session_current_route"] = {"plan_id": "old", "stops": [{"poi_name": "旧地点"}]}

    update = await turn_orchestrate(state)

    assert update["turn_mode"] == "plan"
    assert update["run_mode"] == "plan"
    assert update["route_intent"]["intent_type"] == "new_plan"


@pytest.mark.asyncio
async def test_reject_reply_completes_with_guided_presentation():
    state = build_initial_state("帮我写代码")
    update = await reject_reply(state)

    assert update["run_status"] == "completed"
    assert update["reply_type"] == "reject"
    assert update["presentation"]["highlights"]
    assert update["agent_reply_meta"]["next_suggested_user_moves"]
