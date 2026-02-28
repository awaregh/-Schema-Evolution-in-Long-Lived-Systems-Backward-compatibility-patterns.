-- =============================================================================
-- Migration: 008_event_schema_v2
-- Scenario 6/7: Event log schema evolution – v1 → v2
-- Pattern:    Additive column expansion + JSON payload versioning
-- Safety:     SAFE – all new columns are nullable; v1 event writers remain
--             compatible.  The event_processor service reads both schemas
--             using a schema_version discriminator.
-- Prerequisite: postgres-init.sql (uuid-ossp extension)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- UP
-- -----------------------------------------------------------------------------

-- Create event_logs table if it doesn't already exist (idempotent baseline)
CREATE TABLE IF NOT EXISTS event_logs (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    -- v1 fields
    event_type      VARCHAR(100) NOT NULL,
    entity_type     VARCHAR(50)  NOT NULL,   -- e.g. 'user', 'subscription'
    entity_id       UUID         NOT NULL,
    actor_id        UUID,                    -- user who triggered the event; NULL = system
    payload         JSONB        NOT NULL DEFAULT '{}',
    schema_version  INTEGER      NOT NULL DEFAULT 1,
    occurred_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_event_logs_entity
    ON event_logs (entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_event_logs_event_type
    ON event_logs (event_type);
CREATE INDEX IF NOT EXISTS idx_event_logs_occurred_at
    ON event_logs (occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_event_logs_actor_id
    ON event_logs (actor_id)
    WHERE actor_id IS NOT NULL;

COMMENT ON TABLE  event_logs               IS 'Append-only audit / domain event log; supports v1 and v2 schemas via schema_version.';
COMMENT ON COLUMN event_logs.payload       IS 'Flexible JSON payload. Structure varies by event_type and schema_version.';
COMMENT ON COLUMN event_logs.schema_version IS '1 = original flat payload; 2 = structured payload with metadata envelope.';

-- ---------------------------------------------------------------------------
-- v2 additions: structured metadata + correlation / causation tracking
-- ---------------------------------------------------------------------------

-- Correlation ID links all events that belong to the same logical request
ALTER TABLE event_logs ADD COLUMN IF NOT EXISTS correlation_id UUID;

-- Causation ID points to the event that directly caused this one
ALTER TABLE event_logs ADD COLUMN IF NOT EXISTS causation_id UUID;

-- Service that emitted the event (useful in multi-service architectures)
ALTER TABLE event_logs ADD COLUMN IF NOT EXISTS source_service VARCHAR(100);

-- Structured metadata envelope (replaces ad-hoc payload keys in v2)
-- Schema: {user_agent, ip_address, request_id, feature_flags: {}}
ALTER TABLE event_logs ADD COLUMN IF NOT EXISTS metadata JSONB;

-- v2 events carry an explicit aggregate_version for optimistic concurrency
ALTER TABLE event_logs ADD COLUMN IF NOT EXISTS aggregate_version INTEGER;

-- Indexes for v2 correlation / causation lookups
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_event_logs_correlation_id
    ON event_logs (correlation_id)
    WHERE correlation_id IS NOT NULL;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_event_logs_source_service
    ON event_logs (source_service)
    WHERE source_service IS NOT NULL;

-- GIN index for fast JSONB payload / metadata queries
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_event_logs_payload_gin
    ON event_logs USING GIN (payload);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_event_logs_metadata_gin
    ON event_logs USING GIN (metadata)
    WHERE metadata IS NOT NULL;

COMMENT ON COLUMN event_logs.correlation_id      IS 'v2: links related events across a single business transaction.';
COMMENT ON COLUMN event_logs.causation_id        IS 'v2: UUID of the event that directly caused this event.';
COMMENT ON COLUMN event_logs.source_service      IS 'v2: emitting service name (e.g. users, billing, analytics).';
COMMENT ON COLUMN event_logs.metadata            IS 'v2: structured metadata envelope {user_agent, ip, request_id, feature_flags}.';
COMMENT ON COLUMN event_logs.aggregate_version   IS 'v2: monotonically increasing version of the aggregate at time of event.';

-- -----------------------------------------------------------------------------
-- DOWN
-- -----------------------------------------------------------------------------
-- DROP INDEX CONCURRENTLY IF EXISTS idx_event_logs_metadata_gin;
-- DROP INDEX CONCURRENTLY IF EXISTS idx_event_logs_payload_gin;
-- DROP INDEX CONCURRENTLY IF EXISTS idx_event_logs_source_service;
-- DROP INDEX CONCURRENTLY IF EXISTS idx_event_logs_correlation_id;
-- ALTER TABLE event_logs DROP COLUMN IF EXISTS aggregate_version;
-- ALTER TABLE event_logs DROP COLUMN IF EXISTS metadata;
-- ALTER TABLE event_logs DROP COLUMN IF EXISTS source_service;
-- ALTER TABLE event_logs DROP COLUMN IF EXISTS causation_id;
-- ALTER TABLE event_logs DROP COLUMN IF EXISTS correlation_id;
-- DROP TABLE IF EXISTS event_logs;
