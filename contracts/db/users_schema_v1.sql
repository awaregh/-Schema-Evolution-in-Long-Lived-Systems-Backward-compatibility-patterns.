-- =============================================================================
-- Users Schema – Version 1
-- Documentation DDL (not executed directly; applied via migration scripts)
-- =============================================================================
-- Design notes:
--   • `first_name` / `last_name` are the canonical name columns in v1.
--   • All columns are NOT NULL unless explicitly stated.
--   • Soft-delete is not supported in v1; use status = 'inactive'.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- provides gen_random_uuid()

-- ---------------------------------------------------------------------------
-- enum types
-- ---------------------------------------------------------------------------

CREATE TYPE user_status AS ENUM ('active', 'inactive', 'pending', 'suspended');
CREATE TYPE subscription_plan AS ENUM ('free', 'starter', 'pro', 'enterprise');

-- ---------------------------------------------------------------------------
-- users
-- ---------------------------------------------------------------------------

CREATE TABLE users (
    id          UUID            NOT NULL DEFAULT gen_random_uuid(),
    first_name  VARCHAR(100)    NOT NULL,
    last_name   VARCHAR(100)    NOT NULL,
    email       VARCHAR(254)    NOT NULL,
    phone       VARCHAR(20),                       -- nullable
    status      user_status     NOT NULL DEFAULT 'pending',
    plan        subscription_plan NOT NULL DEFAULT 'free',
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT users_pkey        PRIMARY KEY (id),
    CONSTRAINT users_email_uniq  UNIQUE (email)
);

CREATE INDEX users_status_idx ON users (status);
CREATE INDEX users_plan_idx   ON users (plan);
CREATE INDEX users_created_at_idx ON users (created_at DESC);

-- ---------------------------------------------------------------------------
-- Trigger: keep updated_at current
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE TRIGGER users_set_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- subscriptions (referenced by events)
-- ---------------------------------------------------------------------------

CREATE TABLE subscriptions (
    id              UUID            NOT NULL DEFAULT gen_random_uuid(),
    user_id         UUID            NOT NULL,
    plan            subscription_plan NOT NULL,
    amount_cents    INTEGER         NOT NULL CHECK (amount_cents >= 0),
    currency        CHAR(3)         NOT NULL DEFAULT 'USD',
    billing_period  VARCHAR(10)     NOT NULL CHECK (billing_period IN ('monthly', 'annual')),
    trial_ends_at   TIMESTAMPTZ,
    started_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT subscriptions_pkey          PRIMARY KEY (id),
    CONSTRAINT subscriptions_user_id_fkey  FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX subscriptions_user_id_idx ON subscriptions (user_id);

CREATE TRIGGER subscriptions_set_updated_at
    BEFORE UPDATE ON subscriptions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
