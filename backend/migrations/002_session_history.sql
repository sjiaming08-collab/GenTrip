CREATE INDEX IF NOT EXISTS sessions_by_user_updated
    ON sessions ((payload->>'user_id'), updated_at DESC);

CREATE INDEX IF NOT EXISTS turns_by_session_created
    ON turns (session_id, created_at, turn_id);
