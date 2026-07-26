# Runtime Quality Gates

The release gate is deliberately split into deterministic layers. No production LLM request is required in CI.

| Layer | Command | What it proves |
| --- | --- | --- |
| Constraint language | `python -m pytest backend/tests/test_golden_constraint_cases.py -q` | Natural-language constraints normalize predictably |
| Planning quality | `python -m pytest backend/tests/test_golden_conversations.py -q` | Multi-turn Plan/Replan satisfies declared hard constraints and route-quality thresholds |
| Durable runtime E2E | `python -m pytest backend/tests/test_runtime_e2e_quality.py -q` | Enqueue, worker execution, checkpoints, events, terminal state, and route quality remain coherent |
| Failure injection | `python -m pytest backend/tests/test_run_deadline.py backend/tests/test_redis_stream_worker.py backend/tests/test_session_history_store.py -q` | Deadline, retry/DLQ, CAS, and tenant capacity have defined terminal behavior |

`test_runtime_e2e_quality.py` runs every golden conversation through the same asynchronous path used in production: `start_plan -> queue message -> worker process_message -> persistent run/events/checkpoints`. It uses an in-memory durable transport only to keep the suite deterministic; the production Redis Stream transport is tested separately.

## Required case contract

Every newly added golden turn must declare observable expectations. For route turns this means at least route mode/path, required or forbidden categories, and a `quality` threshold where the fixture can produce a reference route. The deterministic score combines feasibility, rating, travel, diversity, duplicate detection, preference coverage, and exclusion compliance. It cannot grade prose quality.

## Offline judge tier

Keep subjective evaluation separate from the PR gate. A weekly/offline job should use versioned request/route snapshots and a pinned judge prompt/model. Its structured rubric should rate explanation clarity, trade-off disclosure, and match to soft intent. Save the judge model, prompt version, rubric version, input hash, output, and human override; sample disagreements for review. Never make this online, unpinned judge a blocking unit test.
