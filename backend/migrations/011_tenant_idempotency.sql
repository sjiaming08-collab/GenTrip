-- A client retry represents the same accepted request even before a session id
-- has been returned. Idempotency keys are therefore tenant-scoped.

WITH duplicate_keys AS (
    SELECT run_id,
           ROW_NUMBER() OVER (
               PARTITION BY tenant_id, idempotency_key
               ORDER BY created_at, run_id
           ) AS occurrence
    FROM runs
    WHERE idempotency_key IS NOT NULL
)
UPDATE runs
SET idempotency_key = NULL
WHERE run_id IN (
    SELECT run_id FROM duplicate_keys WHERE occurrence > 1
);

DROP INDEX IF EXISTS runs_tenant_session_idempotency_key_idx;
CREATE UNIQUE INDEX IF NOT EXISTS runs_tenant_idempotency_key_idx
    ON runs (tenant_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
