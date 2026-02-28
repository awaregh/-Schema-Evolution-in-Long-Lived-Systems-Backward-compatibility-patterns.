-- =============================================================================
-- Migration: 002_expand_given_name
-- Scenario 1: Rename first_name → given_name  (EXPAND phase)
-- Pattern:    Expand / Contract
-- Safety:     SAFE – adds new nullable columns alongside existing ones.
--             Old application code continues to read/write first_name/last_name.
--             New application code dual-writes all four columns.
--             No data is moved here; see 003_backfill_given_name for that.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- UP
-- -----------------------------------------------------------------------------
-- Add shadow columns; nullable so existing rows are unaffected
ALTER TABLE users ADD COLUMN IF NOT EXISTS given_name  VARCHAR(100);
ALTER TABLE users ADD COLUMN IF NOT EXISTS family_name VARCHAR(100);

-- Partial index: only cover rows that have been backfilled to avoid bloating
-- the index during the transition period.  CONCURRENTLY avoids a full table lock.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_given_name
    ON users (given_name)
    WHERE given_name IS NOT NULL;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_family_name
    ON users (family_name)
    WHERE family_name IS NOT NULL;

COMMENT ON COLUMN users.given_name  IS 'v2 replacement for first_name (expand phase; NULL until backfilled).';
COMMENT ON COLUMN users.family_name IS 'v2 replacement for last_name  (expand phase; NULL until backfilled).';

-- -----------------------------------------------------------------------------
-- DOWN
-- -----------------------------------------------------------------------------
-- DROP INDEX CONCURRENTLY IF EXISTS idx_users_family_name;
-- DROP INDEX CONCURRENTLY IF EXISTS idx_users_given_name;
-- ALTER TABLE users DROP COLUMN IF EXISTS family_name;
-- ALTER TABLE users DROP COLUMN IF EXISTS given_name;
