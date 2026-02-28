-- =============================================================================
-- Migration: 005_subscriptions_baseline
-- Scenario:  Baseline schema (v1) – subscriptions and invoices tables
-- Author:    Schema Evolution Research System
-- =============================================================================

-- -----------------------------------------------------------------------------
-- UP
-- -----------------------------------------------------------------------------
CREATE TABLE subscriptions (
    id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID         NOT NULL,
    plan             VARCHAR(50)  NOT NULL,
    status           VARCHAR(20)  NOT NULL DEFAULT 'active',
    -- v1 monetary representation: integer cents (e.g. 999 = $9.99)
    amount_cents     INTEGER      NOT NULL,
    currency         VARCHAR(3)   NOT NULL DEFAULT 'USD',
    billing_cycle    VARCHAR(20)  NOT NULL DEFAULT 'monthly',
    started_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    ended_at         TIMESTAMPTZ,
    next_billing_date DATE,
    schema_version   INTEGER      NOT NULL DEFAULT 1,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_subscriptions_user_id ON subscriptions (user_id);
CREATE INDEX idx_subscriptions_status  ON subscriptions (status);
CREATE INDEX idx_subscriptions_plan    ON subscriptions (plan);

COMMENT ON TABLE  subscriptions              IS 'User subscriptions; demonstrates integer→decimal type-change pattern.';
COMMENT ON COLUMN subscriptions.amount_cents IS 'v1 monetary column: whole cents (e.g. 999 = $9.99).';
COMMENT ON COLUMN subscriptions.schema_version IS '1 = amount_cents only; 2 = amount shadow column also populated.';

-- ------------------------------------
CREATE TABLE invoices (
    id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    subscription_id  UUID         NOT NULL REFERENCES subscriptions (id) ON DELETE CASCADE,
    user_id          UUID         NOT NULL,
    invoice_number   VARCHAR(50)  NOT NULL,
    -- v1 monetary representation
    amount_cents     INTEGER      NOT NULL,
    currency         VARCHAR(3)   NOT NULL DEFAULT 'USD',
    status           VARCHAR(20)  NOT NULL DEFAULT 'pending',
    issued_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    due_at           TIMESTAMPTZ,
    paid_at          TIMESTAMPTZ,
    line_items       JSONB,
    schema_version   INTEGER      NOT NULL DEFAULT 1,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_invoices_invoice_number ON invoices (invoice_number);
CREATE INDEX        idx_invoices_subscription_id ON invoices (subscription_id);
CREATE INDEX        idx_invoices_user_id         ON invoices (user_id);
CREATE INDEX        idx_invoices_status          ON invoices (status);

COMMENT ON TABLE  invoices              IS 'Billing invoices; mirrors the integer→decimal migration of subscriptions.';
COMMENT ON COLUMN invoices.amount_cents IS 'v1 monetary column.';
COMMENT ON COLUMN invoices.line_items   IS 'JSON array of line-item objects: [{description, quantity, unit_price_cents}].';

-- -----------------------------------------------------------------------------
-- DOWN
-- -----------------------------------------------------------------------------
-- DROP TABLE IF EXISTS invoices;
-- DROP TABLE IF EXISTS subscriptions;
