-- =============================================================================
-- Migration: 003_backfill_given_name
-- Scenario 1: Rename first_name → given_name  (BACKFILL phase)
-- Pattern:    Online / incremental migration
-- Safety:     SAFE when run in small batches via the backfill worker.
--             This file represents the equivalent single-statement version
--             for reference and for small datasets (CI / dev seed).
--             In production, prefer the backfill worker (services/backfill/)
--             which paginates in batches of 1 000 rows to avoid lock contention.
-- Prerequisite: 002_expand_given_name must have been applied.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- UP
-- -----------------------------------------------------------------------------

-- One-shot backfill (suitable for development / small tables).
-- The WHERE clause is idempotent: re-running does nothing if already backfilled.
UPDATE users
SET    given_name     = first_name,
       family_name    = last_name,
       schema_version = 2,
       updated_at     = NOW()
WHERE  given_name IS NULL
  AND  deleted_at IS NULL;

-- Verify – uncomment during manual migration to confirm progress:
-- SELECT schema_version, COUNT(*) FROM users GROUP BY 1 ORDER BY 1;

-- -----------------------------------------------------------------------------
-- DOWN
-- -----------------------------------------------------------------------------
-- Revert rows written by this migration back to NULL (v1 state).
-- Note: rows written by the application after migration are NOT reverted here;
-- a full rollback requires reverting the application code first.
--
-- UPDATE users
-- SET    given_name     = NULL,
--        family_name    = NULL,
--        schema_version = 1,
--        updated_at     = NOW()
-- WHERE  schema_version = 2;
