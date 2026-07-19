-- Tenant scopes all externally visible session and user-profile identifiers.
-- Existing local data is retained in the default tenant during migration.

ALTER TABLE sessions ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE turns ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE runs ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';

ALTER TABLE turns DROP CONSTRAINT IF EXISTS turns_session_id_fkey;
ALTER TABLE runs DROP CONSTRAINT IF EXISTS runs_session_id_fkey;
-- A prior interrupted execution may already have created the tenant-scoped
-- foreign keys below. Drop both names before rebuilding the composite key.
ALTER TABLE turns DROP CONSTRAINT IF EXISTS turns_tenant_session_fkey;
ALTER TABLE runs DROP CONSTRAINT IF EXISTS runs_tenant_session_fkey;
ALTER TABLE sessions DROP CONSTRAINT IF EXISTS sessions_pkey;
ALTER TABLE user_profiles DROP CONSTRAINT IF EXISTS user_profiles_pkey;

ALTER TABLE sessions ADD CONSTRAINT sessions_pkey PRIMARY KEY (tenant_id, session_id);
ALTER TABLE user_profiles ADD CONSTRAINT user_profiles_pkey PRIMARY KEY (tenant_id, user_id);
ALTER TABLE turns ADD CONSTRAINT turns_tenant_session_fkey
    FOREIGN KEY (tenant_id, session_id) REFERENCES sessions (tenant_id, session_id) ON DELETE CASCADE;
ALTER TABLE runs ADD CONSTRAINT runs_tenant_session_fkey
    FOREIGN KEY (tenant_id, session_id) REFERENCES sessions (tenant_id, session_id) ON DELETE CASCADE;

DROP INDEX IF EXISTS runs_session_idempotency_key_idx;
CREATE UNIQUE INDEX IF NOT EXISTS runs_tenant_session_idempotency_key_idx
    ON runs (tenant_id, session_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS sessions_by_tenant_user_updated
    ON sessions (tenant_id, (payload->>'user_id'), updated_at DESC);
CREATE INDEX IF NOT EXISTS turns_by_tenant_session_created
    ON turns (tenant_id, session_id, created_at, turn_id);
