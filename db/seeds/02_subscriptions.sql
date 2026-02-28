-- =============================================================================
-- Seed: 02_subscriptions.sql
-- Purpose: Sample subscriptions and invoices.
--          Mix of v1 rows (amount IS NULL) and v2 rows (amount populated)
--          to demonstrate the integer→decimal backfill scenario.
-- Run after: 005_subscriptions_baseline.sql, 006_expand_amount_decimal.sql,
--            01_users.sql
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Subscriptions
-- ---------------------------------------------------------------------------
INSERT INTO subscriptions (
    id, user_id, plan, status, amount_cents, amount, currency,
    billing_cycle, started_at, next_billing_date, schema_version
)
VALUES
    -- v1 rows: amount IS NULL (not yet backfilled)
    (
        '22222222-0000-0000-0000-000000000001',
        '11111111-0000-0000-0000-000000000002',  -- Bob (pro)
        'pro',
        'active',
        1999,   -- $19.99
        NULL,   -- not yet backfilled
        'USD',
        'monthly',
        NOW() - INTERVAL '6 months',
        (NOW() + INTERVAL '24 days')::DATE,
        1
    ),
    (
        '22222222-0000-0000-0000-000000000002',
        '11111111-0000-0000-0000-000000000003',  -- Carmen (enterprise)
        'enterprise',
        'active',
        49900,  -- $499.00
        NULL,
        'USD',
        'annual',
        NOW() - INTERVAL '3 months',
        (NOW() + INTERVAL '9 months')::DATE,
        1
    ),
    (
        '22222222-0000-0000-0000-000000000003',
        '11111111-0000-0000-0000-000000000005',  -- Emeka (pro)
        'pro',
        'active',
        1999,
        NULL,
        'USD',
        'monthly',
        NOW() - INTERVAL '1 month',
        (NOW() + INTERVAL '30 days')::DATE,
        1
    ),
    -- v2 rows: amount already populated by backfill worker
    (
        '22222222-0000-0000-0000-000000000004',
        '11111111-0000-0000-0000-000000000006',  -- Fatima (pro)
        'pro',
        'active',
        1999,
        19.99,
        'USD',
        'monthly',
        NOW() - INTERVAL '2 months',
        (NOW() + INTERVAL '28 days')::DATE,
        2
    ),
    (
        '22222222-0000-0000-0000-000000000005',
        '11111111-0000-0000-0000-000000000007',  -- George (enterprise)
        'enterprise',
        'active',
        49900,
        499.00,
        'USD',
        'annual',
        NOW() - INTERVAL '5 months',
        (NOW() + INTERVAL '7 months')::DATE,
        2
    ),
    (
        '22222222-0000-0000-0000-000000000006',
        '11111111-0000-0000-0000-000000000010',  -- Jing (enterprise)
        'enterprise',
        'active',
        49900,
        499.00,
        'USD',
        'annual',
        NOW() - INTERVAL '1 month',
        (NOW() + INTERVAL '11 months')::DATE,
        2
    ),
    -- Cancelled subscription
    (
        '22222222-0000-0000-0000-000000000007',
        '11111111-0000-0000-0000-000000000009',  -- Ivan (suspended)
        'pro',
        'cancelled',
        1999,
        NULL,
        'USD',
        'monthly',
        NOW() - INTERVAL '8 months',
        NULL,
        1
    )
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Invoices
-- ---------------------------------------------------------------------------
INSERT INTO invoices (
    id, subscription_id, user_id, invoice_number,
    amount_cents, amount, currency, status,
    issued_at, due_at, paid_at, line_items, schema_version
)
VALUES
    -- Invoice for Bob (v1: amount NULL)
    (
        '33333333-0000-0000-0000-000000000001',
        '22222222-0000-0000-0000-000000000001',
        '11111111-0000-0000-0000-000000000002',
        'INV-2024-0001',
        1999,
        NULL,
        'USD',
        'paid',
        NOW() - INTERVAL '5 months',
        NOW() - INTERVAL '5 months' + INTERVAL '30 days',
        NOW() - INTERVAL '5 months' + INTERVAL '2 days',
        '[{"description": "Pro plan – monthly", "quantity": 1, "unit_price_cents": 1999}]'::JSONB,
        1
    ),
    -- Invoice for Carmen (v1: amount NULL)
    (
        '33333333-0000-0000-0000-000000000002',
        '22222222-0000-0000-0000-000000000002',
        '11111111-0000-0000-0000-000000000003',
        'INV-2024-0002',
        49900,
        NULL,
        'USD',
        'paid',
        NOW() - INTERVAL '3 months',
        NOW() - INTERVAL '3 months' + INTERVAL '30 days',
        NOW() - INTERVAL '3 months' + INTERVAL '5 days',
        '[{"description": "Enterprise plan – annual", "quantity": 1, "unit_price_cents": 49900}]'::JSONB,
        1
    ),
    -- Invoice for Fatima (v2: amount populated)
    (
        '33333333-0000-0000-0000-000000000003',
        '22222222-0000-0000-0000-000000000004',
        '11111111-0000-0000-0000-000000000006',
        'INV-2024-0003',
        1999,
        19.99,
        'USD',
        'paid',
        NOW() - INTERVAL '2 months',
        NOW() - INTERVAL '2 months' + INTERVAL '30 days',
        NOW() - INTERVAL '2 months' + INTERVAL '1 day',
        '[{"description": "Pro plan – monthly", "quantity": 1, "unit_price_cents": 1999}]'::JSONB,
        2
    ),
    -- Upcoming (unpaid) invoice for George
    (
        '33333333-0000-0000-0000-000000000004',
        '22222222-0000-0000-0000-000000000005',
        '11111111-0000-0000-0000-000000000007',
        'INV-2024-0004',
        49900,
        499.00,
        'USD',
        'pending',
        NOW() - INTERVAL '5 months',
        NOW() + INTERVAL '25 days',
        NULL,
        '[{"description": "Enterprise plan – annual", "quantity": 1, "unit_price_cents": 49900}]'::JSONB,
        2
    ),
    -- Overdue invoice for Ivan
    (
        '33333333-0000-0000-0000-000000000005',
        '22222222-0000-0000-0000-000000000007',
        '11111111-0000-0000-0000-000000000009',
        'INV-2024-0005',
        1999,
        NULL,
        'USD',
        'overdue',
        NOW() - INTERVAL '60 days',
        NOW() - INTERVAL '30 days',
        NULL,
        '[{"description": "Pro plan – monthly", "quantity": 1, "unit_price_cents": 1999}]'::JSONB,
        1
    )
ON CONFLICT (id) DO NOTHING;
