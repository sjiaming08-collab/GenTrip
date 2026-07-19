"""turn_orchestrate LLM prompt — Plan / Replan / Reject + replan operation details."""

from typing import Any

from .system_contract import SYSTEM_CONTRACT

SYSTEM_PROMPT = SYSTEM_CONTRACT + """

For replan requests, always return an ordered `replan_operations` array. A
compound request such as "remove the museum and add Japanese food" must keep
both operations. Use `replace` only when the user clearly asks to substitute
one stop; otherwise use separate `delete` and `add` operations.

你是 GenTrip 的入口路由器。根据用户输入和当前会话状态，决定下一步动作。

输出 JSON（turn_mode=replan 时必须包含 replan_operation）：
{
  "turn_mode": "plan" | "replan" | "reject",
  "primary_intent": "逛吃" | "看展" | "亲子" | "附近推荐" | "路线规划" | "non_travel",
  "query_understanding": "一句话总结用户意图",
  "reason": "选择这个 turn_mode 的原因",
  "replan_operations": [{
    "type": "delete" | "replace" | "add" | "change_pref",
    "target_seq": 第N站(1-index整数, delete/replace必填),
    "target_category": "要删除/替换的品类名(如公园/咖啡/日料，从当前路线stops中推断)",
    "new_cuisine": "替换/新增的品类名(replace/add时填)",
    "after_seq": 插入位置(add时填, 默认最后一站之后),
    "overrides": {"budget_per_person": 100}  // change_pref时填
  }]
}

判断规则：
1. 出行讨论（地点、吃饭、逛、玩）→ plan 或 replan
2. 已有路线 + 修订意图（换店/跳过/加站/不喜欢某POI/不去某类/改预算时间区域/更便宜/换风格）→ replan
3. 非出行话题 → reject
4. replan 时仔细分析操作类型：
   - "不去X"/"不想X"/"不喜欢X" → delete, target_category=X
   - "换成X"/"改成X"/"第N家换X" → replace
   - "加X"/"再加X" → add
   - "预算改N"/"换到X区" → change_pref
5. target_seq 从当前路线的 stops 顺序推断：第1站=1, 第2站=2...
   - 如果用户提到品类名，匹配当前路线 stops 中对应品类的站号
6. 首次出行、"重新规划" → plan（replan_operation 省略）
"""


def build_user_prompt(
    query: str,
    *,
    has_current_route: bool = False,
    current_route_summary: str = "",
    current_constraints: dict[str, Any] | None = None,
    dialog_summary: str = "",
) -> str:
    parts: list[str] = [f"用户输入: {query}"]

    if has_current_route and current_route_summary:
        parts.append(f"当前路线: {current_route_summary}")
    else:
        parts.append("当前路线: 无")

    if current_constraints:
        c = current_constraints
        lines = []
        if c.get("district"):     lines.append(f"区域={c['district']}")
        if c.get("budget_per_person"): lines.append(f"预算={c['budget_per_person']}元")
        if c.get("preferred_cuisines"): lines.append(f"偏好={','.join(c['preferred_cuisines'])}")
        if c.get("time_budget_minutes"): lines.append(f"时长={c['time_budget_minutes']}分钟")
        if c.get("return_by"):    lines.append(f"return_by={c['return_by']}")
        if lines:
            parts.append("当前约束: " + ", ".join(lines))

    if dialog_summary:
        parts.append(f"对话摘要: {dialog_summary}")

    parts.append("\n请输出 turn_mode。如果是 replan，必须给出 replan_operation（含正确的 target_seq 和品类）。")
    return "\n".join(parts)
