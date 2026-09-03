# TravelPlanner compatibility evaluation

## Why this is a derived benchmark

TravelPlanner evaluates multi-day trips with intercity transportation, daily
meals, attractions, accommodation, dated inventory, and hard constraints.
GenTrip currently produces a single-city, same-day route. Directly feeding the
official validation set to GenTrip would mostly measure unsupported product
scope, not route-planning quality.

The `gentrip-derived-v1` protocol therefore maintains two separate results:

1. A capability audit records which official dimensions are native, adapted,
   or unsupported.
2. A balanced derived suite maps portable constraints into local Shanghai
   day-route requests and executes the real GenTrip graph.

It never emits an official TravelPlanner Final Pass Rate.

## Mapping

| TravelPlanner dimension | GenTrip treatment |
| --- | --- |
| destination city | deterministically mapped to a Shanghai district |
| 3/5/7 days | mapped to a 3/4/5-hour route budget |
| total trip budget | normalized to a local per-person activity budget |
| cuisine | Chinese -> 本帮菜; other released cuisine labels -> 西餐 |
| attractions and meals | sightseeing and dining route domains |
| people count | retained in the prompt, not a structured GenTrip state field |
| flight/self-driving | unsupported and reported |
| accommodation/house rule/room type | unsupported and reported |
| dated inventory | unsupported and reported |

Cases are sampled by a stable hash from every `(easy|medium|hard, 3|5|7 days)`
cell. Adapter development uses train data; validation is executed without
human reference plans. The official test split is not used locally.

## Commands

```powershell
# Download official files, build 18 cases and 324 isolated evaluation POIs.
D:\conda3\envs\GenTrip\python.exe scripts\import_travelplanner.py --download

# Deterministic full-graph baseline.
D:\conda3\envs\GenTrip\python.exe scripts\evaluate_travelplanner.py

# Live planner model and optional offline LLM judge.
D:\conda3\envs\GenTrip\python.exe scripts\evaluate_travelplanner.py --live-llm
D:\conda3\envs\GenTrip\python.exe scripts\evaluate_travelplanner.py --live-llm --llm-judge --limit 3
```

The evaluator defaults to `backend/fixtures/travelplanner_pois.json`. A
`ContextVar`-scoped override bypasses production PostGIS only for that
evaluation run, so benchmark POIs cannot leak into normal API requests.

For SQL inspection in a disposable benchmark database, the generic importer
can load the same fixture idempotently:

```powershell
$env:DATABASE_URL = "postgresql://gentrip:gentrip@localhost:5432/gentrip_benchmark"
D:\conda3\envs\GenTrip\python.exe backend\scripts\import_poi_fixture.py `
  --fixture backend\fixtures\travelplanner_pois.json `
  --source travelplanner_benchmark
```

Do not import this fixture into a production POI database. Names and source
attributes come from TravelPlanner, but coordinates are deterministic Shanghai
test anchors and are marked `benchmark_derived`.

The report includes completion rate, legal-route rate, route-only case pass
rate, end-to-end pass rate (intent checks and route checks must both pass), mean
route quality, intent/constraint micro and macro pass rates, latency, tokens,
capability coverage, and breakdowns by source difficulty and trip days.

## Interpretation

- Use the official TravelPlanner evaluator only after GenTrip supports its full
  output schema and sandbox tools.
- Compare `gentrip-derived-v1` runs only with the same adapter version, source
  split, case IDs, POI snapshot, model, and prompt versions.
- Keep deterministic hard checks separate from the optional LLM Judge.
- Never tune prompts against validation failures and then publish that same
  validation score as a blind result.
- The five-round report is a development regression result because fixes were
  selected from these 18 validation failures. Keep a new untouched holdout
  before making generalization claims.
