# State-Aware Turn Orchestrator

## Goal

The Turn Orchestrator is the single decision entry point for each user turn.
It interprets the current request against a bounded session snapshot and emits
an auditable `TurnPlan`. It does not retrieve POIs, mutate routes, or validate
feasibility.

This keeps semantic decisions in the LLM while deterministic graph nodes own
data access, route mutation, validation, persistence, and recovery.

## Context contract

`TurnContext` is assembled from authoritative runtime state in this order:

1. Current user message.
2. Active explicit constraints and confirmed stops.
3. Current route and pending change.
4. The five most recent turns and active explicit memory facts.
5. Dialog summary and selected user-profile fields.

The prompt serializer bounds route stops, turn text, memory facts, and profile
fields. Full prompts and raw history are not written to telemetry. Observability
stores only counts, the session version, and a context digest.

## Output contract

The node writes a `TurnPlan` to `GraphState`:

```json
{
  "mode": "replan",
  "objective": "remove the museum and add Japanese food",
  "operations": [
    {"type": "delete", "target_seq": 1, "target_category": "museum"},
    {"type": "add", "after_seq": 2, "new_cuisine": "Japanese"}
  ],
  "affected_stop_seqs": [1],
  "preserve_unmentioned_stops": true,
  "session_version": 7,
  "context_digest": "...",
  "source": "llm"
}
```

Duplicate operations are removed deterministically. The existing
`replan_parse` node treats `TurnPlan.operations` as canonical and only uses its
rule parser when the LLM is unavailable or returns no usable operation.

## Routing and incremental execution

```text
turn_orchestrate
  |-- plan   -> constraint_extract -> full planning path
  |-- replan -> replan_parse -> lock_confirmed -> partial_retrieval
  |             -> local_optimize -> validate_delta -> render_diff
  `-- reject -> reject_reply
```

Cold planning still fuses routing understanding with constraint extraction to
avoid an unnecessary extra model call. Replan uses the context-aware LLM call
because references such as "remove that one" or compound edits require the
current route and conversation state.

Unmentioned stops are locked, only affected slots retrieve candidates, and the
result is committed only after delta validation. Node checkpoints persist the
TurnPlan so a retry resumes without re-running completed decisions.

## Design basis

- LangGraph models workflows as shared State, Nodes, and conditional Edges:
  <https://docs.langchain.com/oss/python/langgraph/graph-api>
- Reducers preserve prior state when nodes return partial updates:
  <https://docs.langchain.com/oss/python/langgraph/use-graph-api>
- Checkpoints support fault-tolerant continuation, while side effects still
  require idempotency:
  <https://docs.langchain.com/oss/python/langgraph/persistence>
- Long conversation state should be trimmed or summarized under a bounded
  context policy:
  <https://docs.langchain.com/oss/python/langgraph/add-memory>
