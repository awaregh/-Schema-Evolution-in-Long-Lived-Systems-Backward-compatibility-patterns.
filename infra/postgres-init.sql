-- postgres-init.sql
-- Initialization script for the schema_evolution database.
-- Runs automatically on first container start via docker-entrypoint-initdb.d.

-- ---------------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements";

-- ---------------------------------------------------------------------------
-- Migration tracking
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_version (
    id          SERIAL PRIMARY KEY,
    service     VARCHAR(50)  NOT NULL,
    version     VARCHAR(20)  NOT NULL,
    applied_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (service, version)
);

COMMENT ON TABLE  schema_version             IS 'Tracks which migration version each service has applied.';
COMMENT ON COLUMN schema_version.service     IS 'Logical service name (e.g. users, billing, analytics).';
COMMENT ON COLUMN schema_version.version     IS 'Migration version identifier (e.g. 001, v1.2.0).';
COMMENT ON COLUMN schema_version.applied_at  IS 'Wall-clock timestamp when the migration was applied.';
