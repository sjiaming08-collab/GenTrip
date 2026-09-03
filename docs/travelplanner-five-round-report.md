# TravelPlanner-derived five-round report

Date: 2026-08-17

## Scope

This report covers a GenTrip-specific derivative of TravelPlanner, not the
official multi-day benchmark. The suite contains 18 balanced cases across all
`(easy, medium, hard) x (3, 5, 7 days)` cells and 324 evaluation-only POIs.
Only 62.8% of active source-constraint dimensions are portable to GenTrip's
current single-city day-route schema.

The five rounds reuse the same 18 cases to diagnose and fix failures. The final
number is therefore a development regression score, not a blind holdout score.

## Local POI catalog

- Source attributes: official `validation_ref_info.jsonl` attraction and
  restaurant records.
- Local mapping: 8 attractions and 10 restaurants per case.
- Taxonomy: GenTrip dining and sightseeing leaf categories.
- Geography: deterministic anchors in 黄浦、徐汇、静安、浦东.
- Isolation: fixture override scoped to the evaluation context; normal API
  requests continue to use configured PostGIS or `fixtures/pois.json`.
- Provenance: every row includes source row, source city, original record and
  `deterministic_benchmark_transform` location provenance.

## Iterations

| Round | Change | Constraint pass | Legal route | Route pass | End-to-end | Mean quality |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | Inject isolated POI catalog | 87.2% | 100.0% | 50.0% | 27.8% | 0.976 |
| 2 | Parse explicit activity count in rule and LLM normalization paths | 100.0% | 100.0% | 50.0% | 50.0% | 0.976 |
| 3 | Generate exact 1-6 stop skeletons | 100.0% | 94.4% | 50.0% | 50.0% | 0.917 |
| 4 | Fix cuisine alternatives, route ranking and RouteBundle shape guards | 100.0% | 94.4% | 66.7% | 66.7% | 0.926 |
| 5 | Allocate dense-plan visit time after travel/queue reserves | 100.0% | 100.0% | 100.0% | 100.0% | 1.000 |

Round 3 intentionally records a regression: generating four slots exposed that
fixed 60/75-minute visits could not fit four activities into five hours. The
final fix keeps a 40-minute lower bound and records the applied visit cap in
`route_generation_meta`.

Raw reports:

```text
.runtime_logs/travelplanner-iteration-1.json
.runtime_logs/travelplanner-iteration-2.json
.runtime_logs/travelplanner-iteration-3.json
.runtime_logs/travelplanner-iteration-4.json
.runtime_logs/travelplanner-iteration-5.json
```

## Live model evaluation

The configured planner LLM was then run on all 18 cases.

| Metric | Result |
| --- | ---: |
| Completion/legal/route/end-to-end pass | 18/18 |
| Constraint micro/macro pass | 100.0% / 100.0% |
| Mean planner latency | 8.111 s |
| P50 / P95 planner latency | 8.059 s / 8.815 s |
| Min / max planner latency | 7.320 s / 9.797 s |
| Planner tokens | 81,010 |
| Successful LLM calls | 54 |

Each online case called `constraint_extract`, `route_evaluate`, and
`route_present`. Session summary was outside the synchronous evaluation result;
the optional Redis summary queue was unavailable in this run.

### LLM Judge sample

Three high-risk cases were selected: four activities, low-budget alternative
cuisines, and hard/seven-day adaptation.

| Metric | Result |
| --- | ---: |
| LLM Judge pass | 3/3 |
| Mean Judge latency | 1.760 s |
| Judge tokens | 6,775 |
| Planner + Judge tokens for these three cases | 20,670 |

The Judge sample is too small for a population claim. The full planner run
verifies LLM-path compatibility; it still reuses development cases and is not
an untouched generalization result.

## Regression status

Focused tests: `45 passed`. Final backend run: `394 passed, 7 failed, 1
skipped`. One failure is Postgres connection refusal because Docker Desktop was
not running. The other six reproduce pre-existing golden failures around
exhibition/coffee opening coverage and Lujiazui business-area relaxation; they
are not hidden by the TravelPlanner fixture.

## Next evaluation step

Freeze this 18-case suite as development data. Build a new untouched holdout
from different source rows, pin the POI snapshot and prompt/model versions, and
run the holdout once per release. Only that result should be used to discuss
generalization.
