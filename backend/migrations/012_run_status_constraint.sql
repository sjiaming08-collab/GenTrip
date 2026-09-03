ALTER TABLE runs DROP CONSTRAINT IF EXISTS runs_status_check;
ALTER TABLE runs ADD CONSTRAINT runs_status_check CHECK (
    status IN ('queued', 'running', 'completed', 'degraded', 'failed', 'cancelled', 'timed_out', 'interrupted')
);
