# Golden Set

`backend/fixtures/golden_conversations.json` is the deterministic acceptance set for Plan/Replan behavior. It uses the local fixture data and disables live LLM calls in pytest.

Each turn asserts route mode, inherited or overridden constraints, route categories, budget, and Replan diff semantics. It can also declare a `quality` object: deterministic checks for route feasibility, POI rating, total and per-leg walking time, queue time, category diversity, and duplicated POIs. The runner reports two 0-100 scores: `score` measures route experience, while `constraint_score` measures feasibility, preference coverage, exclusion compliance, and duplication. `expectation_score` combines them as `0.7 * constraint_score + 0.3 * score`; CI only accepts a route when both hard expectations and declared quality thresholds pass.

The current gate has 40 conversations and 176 turns, plus 80 declarative constraint-language variation cases in `backend/fixtures/golden_constraint_cases.json` and 30 full-loop route-quality/resilience cases. The language set covers boundary clock formats, half-hour/decimal/Chinese durations, fuzzy numeric budgets, cuisine aliases, multi-category exclusions, multi-domain intents, and memory inheritance. Conversation coverage includes Plan/Replan transitions, add, replace, category and ordinal delete, preference reversal, run cancellation, budget override, full replanning, empty routes, memory inheritance, and non-travel rejection. Route cases independently check legality, domain/category coverage, stop count, budget, time, and deterministic fallback after a simulated HTTP travel-provider failure.

`backend/fixtures/local_life_benchmark.json` adds a TravelPlanner-inspired, GenTrip-native end-to-end suite for 10 local-life agents. It contains 120 district/difficulty-stratified Plan cases and 10 three-turn Replan conversations. See [local-life-benchmark.md](local-life-benchmark.md) for its protocol, current results, and reproducible commands. It is not an official TravelPlanner score.

Run it with:

```powershell
D:\conda3\envs\GenTrip\python.exe -m pytest backend/tests/test_golden_conversations.py -q
D:\conda3\envs\GenTrip\python.exe -m pytest backend/tests/test_golden_constraint_cases.py -q
```

When adding a case, use a realistic user utterance, include its full conversation history in one case, and make the expectation observable from the final state. Do not assert a specific POI unless that POI is a product requirement.

`quality` evaluates route mechanics, not subjective writing quality. It now separately exposes schedule continuity, return slack, start slack, and budget utilization, so a route that merely stays below a cap is not automatically considered good. Keep soft preferences such as atmosphere or "适合约会" in a separate LLM-as-judge suite with frozen prompts and sampled human review; do not make that online call part of the deterministic CI gate.

## Quality Contract

Use these fields under a turn's `expect.quality`:

```json
{
  "min_score": 75,
  "min_avg_rating": 4.0,
  "max_total_travel_min": 45,
  "max_leg_travel_min": 30,
  "max_queue_wait_min": 30,
  "min_category_diversity": 0.5,
  "min_preference_coverage": 1.0,
  "min_constraint_score": 90,
  "min_expectation_score": 80,
  "min_return_slack_min": 10,
  "max_start_slack_min": 30,
  "min_budget_utilization": 0.35,
  "max_budget_utilization": 1.0,
  "require_exclusion_compliance": true,
  "require_unique_pois": true
}
```

The deterministic score is only the CI gate. The next tier should be a versioned offline judge set: store frozen route inputs, a structured rubric, and expected preference trade-offs; run it with a pinned judge model and prompt outside the PR-critical path, then sample disagreements for human review. This prevents an online LLM's non-determinism and cost from making the unit-test suite flaky.
