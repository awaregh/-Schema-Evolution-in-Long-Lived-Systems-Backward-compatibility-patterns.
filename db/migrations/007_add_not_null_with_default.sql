-- =============================================================================
-- Migration: 007_add_not_null_with_default
-- Scenario 4: Add a NOT NULL column safely to a live table
-- Pattern:    Three-phase NOT NULL addition (PostgreSQL 11+ compatible)
-- Safety:     Each phase is safe independently; combine them only when ready.
--
-- Phase 1 (this file) – Add the column as nullable WITH DEFAULT.
--   PostgreSQL stores the default as metadata; existing rows get the default
--   value on read without a full table rewrite (PG 11+).
-- Phase 2 – Backfill any rows that have the column NULL (if inserting without
--   the new column was possible during a deployment window).
-- Phase 3 – Add the NOT NULL constraint using a CHECK constraint first
--   (validated in small increments) then ALTER COLUMN SET NOT NULL.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- PHASE 1 – UP: Add nullable column with server-side default (zero table lock)
-- -----------------------------------------------------------------------------

-- Example: adding a 'notification_channel' preference to users
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS notification_channel VARCHAR(20)
        NOT NULL DEFAULT 'email';

COMMENT ON COLUMN users.notification_channel IS
    'Preferred notification delivery channel. Added via three-phase NOT NULL pattern.';

-- Example: adding a 'tax_rate' column to subscriptions
ALTER TABLE subscriptions
    ADD COLUMN IF NOT EXISTS tax_rate NUMERIC(5, 4)
        NOT NULL DEFAULT 0.0000;

COMMENT ON COLUMN subscriptions.tax_rate IS
    'Applicable tax rate fraction (e.g. 0.0875 = 8.75%). Added via three-phase NOT NULL pattern.';

-- -----------------------------------------------------------------------------
-- PHASE 2 – Backfill (run separately or via the backfill worker)
-- -----------------------------------------------------------------------------
-- No-op here because DEFAULT covers all existing rows on PG 11+.
-- For columns where the correct value depends on row data, run:
--
-- UPDATE users
-- SET    notification_channel = CASE WHEN phone IS NOT NULL THEN 'sms' ELSE 'email' END
-- WHERE  notification_channel IS NULL;

-- -----------------------------------------------------------------------------
-- PHASE 3 – Tighten constraint (run in a separate migration after backfill)
-- -----------------------------------------------------------------------------
-- Step 3a: Add a NOT VALID check constraint (acquires ShareUpdateExclusiveLock
--          only; does NOT scan existing rows immediately).
--
-- ALTER TABLE users
--     ADD CONSTRAINT chk_users_notification_channel_not_null
--     CHECK (notification_channel IS NOT NULL) NOT VALID;
--
-- Step 3b: Validate the constraint in the background (scans rows but allows
--          concurrent reads and writes; no AccessExclusiveLock).
--
-- ALTER TABLE users
--     VALIDATE CONSTRAINT chk_users_notification_channel_not_null;
--
-- Step 3c: Once validated, PostgreSQL recognises the constraint as equivalent
--          to NOT NULL, so no further migration is strictly required.
--          Optionally convert to a native NOT NULL (brief AccessExclusiveLock):
--
-- ALTER TABLE users
--     ALTER COLUMN notification_channel SET NOT NULL;
-- ALTER TABLE users
--     DROP CONSTRAINT IF EXISTS chk_users_notification_channel_not_null;

-- -----------------------------------------------------------------------------
-- DOWN
-- -----------------------------------------------------------------------------
-- ALTER TABLE subscriptions DROP COLUMN IF EXISTS tax_rate;
-- ALTER TABLE users          DROP COLUMN IF EXISTS notification_channel;
