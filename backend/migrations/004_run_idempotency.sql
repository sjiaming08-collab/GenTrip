ALTER TABLE runs ADD COLUMN IF NOT EXISTS idempotency_key TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS runs_session_idempotency_key_idx
    ON runs (session_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
