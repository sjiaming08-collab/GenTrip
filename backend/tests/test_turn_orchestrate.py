import pytest

from src.graph.nodes.turn_orchestrate import turn_orchestrate
from src.graph.nodes.reject_reply import reject_reply
from src.graph.state import build_initial_state


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
async def test_reject_reply_completes_with_guided_presentation():
    state = build_initial_state("帮我写代码")
    update = await reject_reply(state)

    assert update["run_status"] == "completed"
    assert update["reply_type"] == "reject"
    assert update["presentation"]["highlights"]
    assert update["agent_reply_meta"]["next_suggested_user_moves"]
