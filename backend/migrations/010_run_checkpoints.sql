-- Recovery metadata is deliberately separated from final run results.  A
-- checkpoint contains graph state needed for diagnosis/retry, never prompts or
-- credentials, and remains available after a run becomes terminal.
CREATE TABLE IF NOT EXISTS run_checkpoints (
    checkpoint_id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    tenant_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    phase_index INTEGER NOT NULL,
    state JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, phase_index)
);

CREATE INDEX IF NOT EXISTS run_checkpoints_by_tenant_run
    ON run_checkpoints (tenant_id, run_id, phase_index);
