from src.llm.prompts.constraint_extract import build_user_prompt


def test_constraint_prompt_supports_leisure_domain():
    prompt = build_user_prompt("\u9ec4\u6d66\u533a\u73a9\u4e94\u4e2a\u5c0f\u65f6")

    assert "leisure" in prompt
    assert "time_budget_minutes=300" in prompt
