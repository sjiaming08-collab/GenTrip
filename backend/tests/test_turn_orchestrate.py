import pytest

from src.graph.nodes import turn_orchestrate as turn_orchestrate_module
from src.graph.nodes.turn_orchestrate import turn_orchestrate
from src.graph.nodes.reject_reply import reject_reply
from src.graph.state import build_initial_state
from src.llm.turn_classify import LlmReplanOp, LlmTurnDecision
from src.llm.prompts.turn_classify import build_user_prompt


@pytest.mark.asyncio
async def test_turn_orchestrate_rejects_non_travel_query():
    state = build_initial_state("今天股票怎么样")
    update = await turn_orchestrate(state)

    assert update["turn_mode"] == "reject"
    assert update["route_intent"]["intent_type"] == "non_travel"


@pytest.mark.asyncio
async def test_turn_orchestrate_detects_replan_with_current_route():
    state = build_initial_state("不要这家店，换一家咖啡")
    state["session_current_route"] = {"plan_id": "old", "stops": [{"poi_id": "old-poi"}]}
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
async def test_turn_orchestrate_treats_scoped_meal_fragment_as_contextual_replan_when_llm_fails(monkeypatch):
    async def llm_failure(*_args, **_kwargs):
        return (
            LlmTurnDecision(turn_mode="plan"),
            {"operation": "turn_classify", "status": "failed", "fallback_used": True},
        )

    monkeypatch.setattr(turn_orchestrate_module, "classify_turn", llm_failure)
    state = build_initial_state("中午想吃正餐")
    state["session_current_route"] = {
        "plan_id": "old",
        "stops": [
            {"poi_name": "西湖景点", "slot_role": "anchor"},
            {"poi_name": "原午餐", "slot_role": "meal", "slot_id": "bp-meal-lunch"},
            {"poi_name": "文化体验", "slot_role": "anchor"},
        ],
    }
    state["memory_context"] = {
        "current_constraints": {
            "city": "杭州市",
            "time_scope": "full_day",
            "target_duration_minutes": 540,
        }
    }

    update = await turn_orchestrate(state)

    assert update["turn_mode"] == "replan"
    assert update["run_mode"] == "replan"
    assert update["turn_plan"]["preserve_unmentioned_stops"] is True
    assert update["turn_plan"]["source"] == "rule_fallback"
    assert update["turn_relation"] == "modify_current"
    assert update["recompute_scope"] == "slot_only"


@pytest.mark.asyncio
async def test_turn_orchestrate_separates_schedule_revision_from_new_goal(monkeypatch):
    async def llm_failure(*_args, **_kwargs):
        return LlmTurnDecision(), {"operation": "turn_classify", "status": "failed"}

    monkeypatch.setattr(turn_orchestrate_module, "classify_turn", llm_failure)
    state = build_initial_state("少走路，晚一点回来")
    state["session_current_route"] = {
        "plan_id": "old",
        "stops": [{"poi_id": "p1", "poi_name": "西湖", "slot_role": "anchor"}],
    }

    update = await turn_orchestrate(state)

    assert update["turn_mode"] == "replan"
    assert update["turn_relation"] == "modify_current"
    assert update["recompute_scope"] == "schedule_route"


@pytest.mark.asyncio
async def test_turn_orchestrate_explicit_new_route_is_new_goal(monkeypatch):
    async def llm_failure(*_args, **_kwargs):
        return LlmTurnDecision(), {"operation": "turn_classify", "status": "failed"}

    monkeypatch.setattr(turn_orchestrate_module, "classify_turn", llm_failure)
    state = build_initial_state("原来的不要了，另外做一条苏州路线")
    state["session_current_route"] = {"plan_id": "old", "stops": [{"poi_id": "p1"}]}

    update = await turn_orchestrate(state)

    assert update["turn_mode"] == "plan"
    assert update["turn_relation"] == "new_goal"
    assert update["recompute_scope"] == "global_rebuild"


@pytest.mark.asyncio
async def test_turn_orchestrate_rebuilds_current_goal_without_losing_replan_identity(monkeypatch):
    async def llm_failure(*_args, **_kwargs):
        return LlmTurnDecision(), {"operation": "turn_classify", "status": "failed"}

    monkeypatch.setattr(turn_orchestrate_module, "classify_turn", llm_failure)
    state = build_initial_state("重新规划当前路线，其他需求不变")
    state["session_current_route"] = {"plan_id": "old", "stops": [{"poi_id": "p1"}]}

    update = await turn_orchestrate(state)

    assert update["turn_mode"] == "replan"
    assert update["turn_relation"] == "modify_current"
    assert update["recompute_scope"] == "global_rebuild"


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
        "confidence": 1.0,
        "source": "llm",
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
async def test_turn_orchestrate_injects_global_context_and_deduplicates_operations(monkeypatch):
    captured = {}

    async def llm_decision(*_args, **kwargs):
        captured.update(kwargs["turn_context"])
        duplicate = LlmReplanOp(type="add", after_seq=2, new_cuisine="日料")
        return (
            LlmTurnDecision(
                turn_mode="replan",
                primary_intent="路线修改",
                objective="删除美术馆并增加日料",
                affected_stop_seqs=[1],
                replan_operations=[
                    LlmReplanOp(type="delete", target_seq=1, target_category="美术馆"),
                    duplicate,
                    duplicate,
                ],
            ),
            {"operation": "turn_classify", "status": "success", "model": "test-model"},
        )

    monkeypatch.setattr(turn_orchestrate_module, "classify_turn", llm_decision)
    state = build_initial_state("删除美术馆，再增加一家日料")
    state["session_current_route"] = {
        "plan_id": "route-1",
        "stops": [
            {"sequence": 1, "poi_id": "art-1", "poi_name": "当代美术馆", "category": "美术馆"},
            {"sequence": 2, "poi_id": "park-1", "poi_name": "城市公园", "category": "公园"},
        ],
    }
    state["memory_context"] = {
        "session_version": 7,
        "session_mode": "reviewing",
        "current_constraints": {"district": "黄浦区", "time_budget_minutes": 180},
        "confirmed_stop_ids": ["park-1"],
        "rejected_poi_ids": ["old-1"],
        "recent_turns": [{"turn_id": "t-1", "user_query": "想看展", "assistant_message": "已规划"}],
        "dialog_summary": "用户正在调整黄浦区路线",
        "memory_facts": [{"slot": "district", "value": "黄浦区", "source": "explicit_user"}],
        "user_profile": {"preferred_cuisines": ["日料"]},
        "pending_change": {"operations": [{"type": "replace"}]},
    }

    update = await turn_orchestrate(state)

    assert captured["identity"]["session_version"] == 7
    assert captured["confirmed_stop_ids"] == ["park-1"]
    assert captured["recent_turns"][0]["user_query"] == "想看展"
    assert [item["type"] for item in update["turn_plan"]["operations"]] == ["delete", "add"]
    assert update["turn_plan"]["affected_stop_seqs"] == [1]
    assert update["turn_plan"]["preserve_unmentioned_stops"] is True
    assert update["turn_context_meta"]["session_version"] == 7
    assert update["turn_context_meta"]["context_digest"]


def test_turn_prompt_compacts_route_and_history():
    context = {
        "identity": {"session_version": 3},
        "current_message": "修改路线",
        "current_route": {
            "plan_id": "r-1",
            "stops": [
                {"sequence": index + 1, "poi_id": f"p-{index}", "poi_name": f"POI-{index}", "category": "景点"}
                for index in range(12)
            ],
        },
        "active_constraints": {"district": "黄浦区", "unknown": "drop-me"},
        "recent_turns": [
            {"turn_id": f"t-{index}", "user_query": f"q-{index}", "assistant_message": "a"}
            for index in range(8)
        ],
        "memory_facts": [{"slot": "budget", "value": index} for index in range(20)],
    }

    prompt = build_user_prompt("修改路线", turn_context=context)
    payload = __import__("json").loads(prompt.split("\n", 1)[1])

    assert len(payload["current_route"]["stops"]) == 8
    assert [item["turn_id"] for item in payload["recent_turns"]] == [f"t-{index}" for index in range(3, 8)]
    assert len(payload["memory_facts"]) == 12
    assert "unknown" not in payload["active_constraints"]


@pytest.mark.asyncio
async def test_reject_reply_completes_with_guided_presentation():
    state = build_initial_state("帮我写代码")
    update = await reject_reply(state)

    assert update["run_status"] == "completed"
    assert update["reply_type"] == "reject"
    assert update["presentation"]["highlights"]
    assert update["agent_reply_meta"]["next_suggested_user_moves"]
