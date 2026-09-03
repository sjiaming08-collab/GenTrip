# GenTrip LocalLifeBench

## Purpose

LocalLifeBench adapts TravelPlanner's core evaluation idea, constraint-grounded itinerary generation, to GenTrip's single-city local-life domain. It does not copy TravelPlanner records and must not be reported as an official TravelPlanner score.

The benchmark answers four separate questions:

1. Did the Agent recover the user's structured constraints?
2. Is the returned route legal under budget, time, return deadline, queue, exclusion, opening-hours, and uniqueness rules?
3. Does the route cover the requested activity categories with enough stops and acceptable route quality?
4. Across multiple turns, did Replan perform the requested add or replace operation without losing the session route?

## Dataset

The versioned fixture is `backend/fixtures/local_life_benchmark.json` and is generated from `backend/src/evaluation/local_life.py`.

- 10 agents: food, city walk, culture, shopping, massage, beauty, sports, gaming, performance, and family activities.
- 120 single-turn Plan cases: 10 agents x 4 Shanghai districts x 3 difficulty levels.
- 10 multi-turn conversations and 30 total turns: initial Plan, category replacement, then cross-domain coffee insertion.
- Development/validation/test split is district-stratified for single turns and agent-stratified for conversations.
- The POI snapshot is `backend/fixtures/pois.json`; every agent/district pair must contain at least two native category POIs.
- Evaluation time is fixed at `2026-08-18T03:00:00+00:00` so weekday and opening-hours checks are reproducible.

Easy cases cover one category plus duration, budget, and stop count. Medium cases combine activity and dining with explicit start time and queue tolerance. Hard cases add return deadline, exclusion, category order, and tighter feasibility constraints. Massage and beauty hard cases use three stops because requiring two repeated service appointments would lower route realism rather than increase useful difficulty.

## Scoring

Deterministic checks are the CI authority for hard constraints. The route quality score combines legality, requested category coverage, stop count, budget, time, and relaxation penalties. LLM Judge is optional and remains outside the PR-critical path.

The LocalLifeBench gate is:

| Metric | Minimum |
| --- | ---: |
| Constraint pass rate | 0.98 |
| Single-turn end-to-end pass rate | 0.90 |
| Mean route quality | 0.90 |
| Multi-turn pass rate by turn | 0.95 |

## Verified Results

Measured locally on 2026-08-17 using the committed POI fixture:

| Tier | Scope | Result |
| --- | --- | --- |
| Deterministic Plan | 120 cases | constraints 100%; route/E2E 91.7%; mean quality 0.921 |
| Deterministic Replan | 10 conversations, 30 turns | conversations 100%; turns 100% |
| Live DeepSeek smoke | one easy case per agent, 10 cases | constraints 100%; E2E 100%; mean latency 7.54 s; 35,953 total tokens |
| Focused regression | retrieval, generation, cache, Replan, constraints, route eval | 90/90 passed |
| Backend regression | all tests except explicit runtime integrations | 412 passed; 3 deselected |

The deterministic failures are retained as capability gaps rather than rewritten into easy passes. They come from combined budget/opening-hour infeasibility and sparse service-category coverage, with most hard failures occurring on four-stop routes. The live result is a 10-case smoke test, not a replacement for the 120-case deterministic score.

The PostgreSQL runtime integration was not included in the final local regression because the configured database endpoint refused connections and `docker compose ps` timed out. No database-integration claim is derived from this run.

Detailed local reports are written under `.runtime_logs/` and are intentionally not the benchmark source of truth.

## Commands

Rebuild and validate the dataset:

```powershell
D:\conda3\envs\GenTrip\python.exe scripts\build_local_life_benchmark.py
$env:PYTHONPATH = "backend"
D:\conda3\envs\GenTrip\python.exe -m pytest backend\tests\test_local_life_benchmark.py -q
```

Run deterministic Plan and Replan gates:

```powershell
D:\conda3\envs\GenTrip\python.exe scripts\evaluate_local_life.py --single-only --quiet --enforce-gate --json-output .runtime_logs\local-life-deterministic-final.json
D:\conda3\envs\GenTrip\python.exe scripts\evaluate_local_life.py --conversations-only --quiet --enforce-gate --json-output .runtime_logs\local-life-conversations-final.json
```

Run a real-model sample for selected cases:

```powershell
D:\conda3\envs\GenTrip\python.exe scripts\evaluate_local_life.py --case-id llb-food-1-easy --case-id llb-culture-1-easy --single-only --live-llm --json-output .runtime_logs\local-life-live-sample.json
```

Add `--llm-judge` only for an offline judged run. It invokes another model pass per case and should not be enabled in deterministic CI.
