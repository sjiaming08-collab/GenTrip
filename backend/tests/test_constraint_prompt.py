from src.llm.prompts.constraint_extract import SYSTEM_PROMPT, build_user_prompt


def test_constraint_prompt_is_current_turn_explicit_only():
    prompt = build_user_prompt(
        "黄浦区玩五个小时",
        user_lat=31.2,
        user_lng=121.4,
        memory_context={"dialog_summary": "上一轮在杭州", "assumptions": ["旧值"]},
    )

    assert '"query":"黄浦区玩五个小时"' in prompt
    assert "domains_explicit" in prompt
    assert "time_expression" in prompt
    assert "time_budget_minutes_explicit" not in prompt
    assert "location_mentions_explicit" not in prompt
    assert "evidence" in prompt
    assert "上一轮在杭州" not in prompt
    assert "31.2" not in prompt
    assert "默认值" not in prompt
    assert '"assumptions"' not in prompt


def test_constraint_prompt_uses_dynamic_geography_without_guessing():
    prompt = SYSTEM_PROMPT + build_user_prompt("杭州西湖附近喝咖啡")

    assert '"city_explicit": "string|null"' in prompt
    assert '"district_explicit": "string|null"' in prompt
    assert "地点按最具体表达提取" in prompt
    assert "禁止猜地点" in prompt
    assert "district 只能是" not in prompt
    assert "支持的 district" not in prompt


def test_constraint_prompt_is_bounded_and_does_not_own_planning():
    prompt = SYSTEM_PROMPT + build_user_prompt("情侣在西湖附近玩一天")

    assert len(prompt) < 2100
    assert "不得输出 POI 名称" in prompt
    assert "路线方案" in prompt
    assert "anchor_count_explicit" in prompt
