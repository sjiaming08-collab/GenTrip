"""匹配评分节点 — 计算最佳模板匹配度 + 分支决策

职责:
  1. 遍历 candidate_templates，计算 match_score
  2. 选最佳匹配
  3. decide_branch() 函数根据阈值决定走哪个分支

匹配公式:
  matchScore = 0.30 × cosineSimilarity
             + 0.20 × districtMatch
             + 0.15 × durationMatch
             + 0.15 × budgetMatch
             + 0.10 × cuisineOverlap
             + 0.10 × scenarioMatch
"""

from ..state import GraphState

# 匹配阈值（可从配置读取）
MATCH_THRESHOLD = 0.75


def compute_match_score(template, intent) -> float:
    """计算模板与意图的匹配分数 [0.0, 1.0]"""
    # TODO: 实现多维匹配评分
    # 1. cosine_similarity(query_vec, template.query_embedding)
    # 2. district_match: intent.district == template.district ? 1.0 : 0.3
    # 3. duration_match: 1 - abs(intent.duration - template.duration) / intent.duration
    # 4. budget_match: 类似
    # 5. cuisine_overlap: jaccard(intent.cuisines, template.cuisine_tags)
    # 6. scenario_match: 基于场景标签的简单匹配
    raise NotImplementedError


async def match_score(state: GraphState) -> dict:
    """
    输入: state["candidate_templates"], state["route_intent"],
          state["query_embedding"]
    输出: best_template, match_score, branch, current_phase="match_score"
    """
    # TODO: 实现
    # 1. 对每个 template 计算 match_score
    # 2. 选最高分
    # 3. branch = "adapt" if score >= MATCH_THRESHOLD else "generate"
    raise NotImplementedError


def decide_branch(state: GraphState) -> str:
    """LangGraph 条件边决策函数 — 返回 "adapt" 或 "generate" """
    return state.get("branch", "generate")
