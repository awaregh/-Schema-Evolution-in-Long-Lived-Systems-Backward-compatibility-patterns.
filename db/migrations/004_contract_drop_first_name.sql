-- =============================================================================
-- Migration: 004_contract_drop_first_name
-- Scenario 1: Rename first_name → given_name  (CONTRACT phase)
-- Pattern:    Expand / Contract
-- Safety:     ⚠️  UNSAFE if applied before ALL consumers have migrated.
--             Only run AFTER:
--               1. 002 and 003 have been applied.
--               2. The backfill worker has confirmed 0 NULL given_name rows.
--               3. Every service version reading first_name / last_name has
--                  been decommissioned (dual-write period has ended).
--             Dropping a column is irreversible without a restore from backup.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- UP
-- -----------------------------------------------------------------------------
ALTER TABLE users DROP COLUMN IF EXISTS first_name;
ALTER TABLE users DROP COLUMN IF EXISTS last_name;

-- Update the schema_version default so new rows are tagged v3 (contract complete)
ALTER TABLE users ALTER COLUMN schema_version SET DEFAULT 3;

COMMENT ON COLUMN users.schema_version IS 'Schema version (3 = contract complete; given_name/family_name are canonical).';

-- -----------------------------------------------------------------------------
-- DOWN
-- -----------------------------------------------------------------------------
-- Re-add the dropped columns and restore data from shadow columns.
-- Data loss is possible if given_name / family_name were ever NULL.
--
-- ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name VARCHAR(100);
-- ALTER TABLE users ADD COLUMN IF NOT EXISTS last_name  VARCHAR(100);
-- UPDATE users SET first_name = given_name, last_name = family_name;
-- ALTER TABLE users ALTER COLUMN schema_version SET DEFAULT 1;
