-- =============================================================================
-- Migration: 001_users_baseline
-- Scenario:  Baseline schema (v1) – initial users table
-- Author:    Schema Evolution Research System
-- =============================================================================

-- -----------------------------------------------------------------------------
-- UP
-- -----------------------------------------------------------------------------
-- Enable uuid generation if not already present (idempotent)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE users (
    id             UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    first_name     VARCHAR(100) NOT NULL,
    last_name      VARCHAR(100) NOT NULL,
    email          VARCHAR(255) NOT NULL,
    phone          VARCHAR(50),
    status         VARCHAR(20)  NOT NULL DEFAULT 'active',
    plan           VARCHAR(50)  NOT NULL DEFAULT 'free',
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at     TIMESTAMPTZ,
    schema_version INTEGER      NOT NULL DEFAULT 1
);

-- Uniqueness on email (active rows only)
CREATE UNIQUE INDEX idx_users_email
    ON users (email)
    WHERE deleted_at IS NULL;

-- Fast lookups by status and plan for analytics queries
CREATE INDEX idx_users_status ON users (status);
CREATE INDEX idx_users_plan   ON users (plan);

COMMENT ON TABLE  users                IS 'Central users table; tracks schema_version per row for expand/contract research.';
COMMENT ON COLUMN users.schema_version IS 'Schema version that last wrote this row (1=v1 first_name/last_name era).';

-- -----------------------------------------------------------------------------
-- DOWN
-- -----------------------------------------------------------------------------
-- DROP INDEX IF EXISTS idx_users_plan;
-- DROP INDEX IF EXISTS idx_users_status;
-- DROP INDEX IF EXISTS idx_users_email;
-- DROP TABLE IF EXISTS users;
