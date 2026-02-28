-- =============================================================================
-- Users Schema – Version 2
-- Documentation DDL (not executed directly; applied via migration scripts)
-- =============================================================================
-- Design notes (Expand-Contract pattern):
--
--   Phase 1 – Expand  (this file / migration V002)
--     • Add `given_name` / `family_name` columns as NULLable.
--     • Add `display_name` / `locale` optional columns.
--     • Add `amount` column (NUMERIC) to subscriptions alongside `amount_cents`.
--     • Back-fill new columns from old values.
--     • Application writes BOTH old and new columns (dual-write).
--
--   Phase 2 – Migrate
--     • Set NOT NULL constraint on `given_name` / `family_name` once backfill done.
--     • Application reads from new columns only.
--
--   Phase 3 – Contract  (future migration V003)
--     • Drop deprecated columns `first_name`, `last_name`, `amount_cents`.
--
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Phase 1: Add new canonical name columns (NULLable during transition)
-- ---------------------------------------------------------------------------

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS given_name   VARCHAR(100),   -- will be NOT NULL after backfill
    ADD COLUMN IF NOT EXISTS family_name  VARCHAR(100),   -- will be NOT NULL after backfill
    ADD COLUMN IF NOT EXISTS display_name VARCHAR(200),
    ADD COLUMN IF NOT EXISTS locale       VARCHAR(10);

-- Deprecation marker (comment only; enforced at application layer)
COMMENT ON COLUMN users.first_name IS 'DEPRECATED since v2. Use given_name. Will be dropped in v3.';
COMMENT ON COLUMN users.last_name  IS 'DEPRECATED since v2. Use family_name. Will be dropped in v3.';

-- ---------------------------------------------------------------------------
-- Phase 1: Back-fill new columns from existing data
-- ---------------------------------------------------------------------------

UPDATE users
SET    given_name  = first_name,
       family_name = last_name
WHERE  given_name IS NULL
   OR  family_name IS NULL;

-- ---------------------------------------------------------------------------
-- Phase 2: Enforce NOT NULL once all rows are populated
-- (Run this after verifying zero NULL rows in production)
-- ---------------------------------------------------------------------------

ALTER TABLE users
    ALTER COLUMN given_name  SET NOT NULL,
    ALTER COLUMN family_name SET NOT NULL;

-- ---------------------------------------------------------------------------
-- Phase 1: Add decimal amount column to subscriptions (NULLable during transition)
-- ---------------------------------------------------------------------------

ALTER TABLE subscriptions
    ADD COLUMN IF NOT EXISTS amount NUMERIC(12, 2);

COMMENT ON COLUMN subscriptions.amount_cents IS 'DEPRECATED since v2. Use amount. Will be dropped in v3.';

-- Back-fill amount from amount_cents
UPDATE subscriptions
SET    amount = (amount_cents::NUMERIC / 100)
WHERE  amount IS NULL;

-- Enforce NOT NULL after back-fill
ALTER TABLE subscriptions
    ALTER COLUMN amount SET NOT NULL;

-- ---------------------------------------------------------------------------
-- Indexes on new columns
-- ---------------------------------------------------------------------------

CREATE INDEX CONCURRENTLY IF NOT EXISTS users_given_name_idx
    ON users (given_name);

CREATE INDEX CONCURRENTLY IF NOT EXISTS users_family_name_idx
    ON users (family_name);

-- ---------------------------------------------------------------------------
-- Final schema state after Phase 2
-- (shows both old and new columns present simultaneously)
-- ---------------------------------------------------------------------------

-- TABLE users
-- ├─ id            UUID          NOT NULL  PK
-- ├─ given_name    VARCHAR(100)  NOT NULL  <-- v2 canonical
-- ├─ family_name   VARCHAR(100)  NOT NULL  <-- v2 canonical
-- ├─ first_name    VARCHAR(100)  NOT NULL  DEPRECATED (alias)
-- ├─ last_name     VARCHAR(100)  NOT NULL  DEPRECATED (alias)
-- ├─ display_name  VARCHAR(200)            <-- new in v2
-- ├─ locale        VARCHAR(10)             <-- new in v2
-- ├─ email         VARCHAR(254)  NOT NULL  UNIQUE
-- ├─ phone         VARCHAR(20)
-- ├─ status        user_status   NOT NULL
-- ├─ plan          subscription_plan NOT NULL
-- ├─ created_at    TIMESTAMPTZ   NOT NULL
-- └─ updated_at    TIMESTAMPTZ   NOT NULL
--
-- TABLE subscriptions
-- ├─ id              UUID          NOT NULL  PK
-- ├─ user_id         UUID          NOT NULL  FK → users
-- ├─ plan            subscription_plan NOT NULL
-- ├─ amount          NUMERIC(12,2) NOT NULL  <-- v2 canonical
-- ├─ amount_cents    INTEGER       NOT NULL  DEPRECATED (alias)
-- ├─ currency        CHAR(3)       NOT NULL
-- ├─ billing_period  VARCHAR(10)   NOT NULL
-- ├─ trial_ends_at   TIMESTAMPTZ
-- ├─ started_at      TIMESTAMPTZ   NOT NULL
-- ├─ created_at      TIMESTAMPTZ   NOT NULL
-- └─ updated_at      TIMESTAMPTZ   NOT NULL
