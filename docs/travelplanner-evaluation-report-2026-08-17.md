# TravelPlanner-derived evaluation report

> Historical pre-fix baseline. The five-round implementation and current
> results are documented in `travelplanner-five-round-report.md`.

Date: 2026-08-17

## Scope

This is a real execution of GenTrip under the `gentrip-derived-v1` compatibility
protocol. It is not an official TravelPlanner submission or Final Pass Rate.

Official train and validation source files were downloaded from
`osunlp/TravelPlanner`, checked against pinned SHA-256 digests, and retained
locally under `data/travelplanner/raw/`. The adapter used the released metadata
to build 18 validation cases: two cases from every `(easy, medium, hard) x
(3, 5, 7 days)` cell. Reference information was not used to construct answers.

## Deterministic baseline

Command:

```powershell
D:\conda3\envs\GenTrip\python.exe scripts\evaluate_travelplanner.py `
  --json-output .runtime_logs\travelplanner-derived-deterministic.json
```

| Metric | Result |
| --- | ---: |
| Cases | 18 |
| Completion rate | 100.0% |
| Legal-route rate | 83.3% |
| Intent/constraint micro pass rate | 87.2% |
| Intent/constraint macro pass rate | 87.2% |
| Route-only case pass rate | 38.9% |
| End-to-end pass rate | 16.7% |
| Mean deterministic route-quality score | 0.881 |
| Mean planner latency | 1.642 s |
| Mean portable source-constraint coverage | 62.8% |

Observed failure signals:

- `poi_count` was extracted incorrectly in 12 of 18 cases.
- Eight routes contained fewer activities than requested.
- Four returned stops were outside the requested district.
- Two routes missed a requested mapped cuisine.
- One low-budget case produced no route.

## Live LLM and Judge sample

Three cases were selected before execution: one easy/3-day, one medium/5-day,
and one hard/7-day source case.

```powershell
D:\conda3\envs\GenTrip\python.exe scripts\evaluate_travelplanner.py `
  --live-llm --llm-judge `
  --case-id tp-validation-017 `
  --case-id tp-validation-091 `
  --case-id tp-validation-176 `
  --json-output .runtime_logs\travelplanner-derived-live-3.json
```

| Metric | Result |
| --- | ---: |
| Completion rate | 100.0% |
| Intent/constraint micro and macro pass rate | 100.0% |
| Legal-route rate | 66.7% |
| Route-only and end-to-end pass rate | 33.3% |
| Mean route-quality score | 0.854 |
| LLM Judge pass rate | 33.3% |
| Mean LLM Judge normalized score | 0.613 |
| Mean planner latency | 10.629 s |
| Mean Judge latency | 1.705 s |
| Planner tokens | 11,868 |
| Judge tokens | 6,586 |
| Total model tokens | 18,454 |

The online planner used `deepseek-v4-flash` for constraint extraction and route
presentation, and `deepseek-v4-pro` for route evaluation. The Judge used
`deepseek-v4-flash`. All three online cases extracted the adapted constraints
correctly. Two still failed downstream: one returned three activities instead
of four; one returned two activities instead of three and both stops were in
the wrong district. The deterministic checker and LLM Judge agreed on all three
verdicts.

## Conclusions

The online LLM materially improves intent extraction, but the current primary
bottleneck is deterministic planning after extraction: candidate retrieval can
escape the requested district, route generation does not reliably honor the
requested stop count, and validation does not reject district mismatches. These
must be fixed before scaling the online sample.

The complete backend regression run finished with `385 passed, 6 failed, 3
deselected`. All new TravelPlanner tests passed. The six existing-suite failures
come from four underlying scenarios: two exhibition/coffee Golden conversations
(also repeated by durable-runtime E2E), `huangpu_exhibit_coffee_return_by`
generating no route, and the Lujiazui RouteBundle case relaxing a business-area
request to citywide after no local candidate route was found. These are outside
the new adapter path, but reinforce the same retrieval and geographic-boundary
findings and should be fixed before using this suite as a blocking CI gate.
