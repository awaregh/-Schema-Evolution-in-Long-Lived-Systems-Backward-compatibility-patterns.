-- =============================================================================
-- Seed: 03_events.sql
-- Purpose: Sample domain events demonstrating v1 and v2 schema evolution.
--          v1 events: flat payload, no correlation/causation/metadata columns.
--          v2 events: structured payload envelope, correlation_id, causation_id,
--                     source_service, metadata, aggregate_version.
-- Run after: 008_event_schema_v2.sql, 01_users.sql, 02_subscriptions.sql
-- =============================================================================

-- ---------------------------------------------------------------------------
-- v1 Events (schema_version = 1, flat payload, no v2 columns)
-- ---------------------------------------------------------------------------
INSERT INTO event_logs (
    id, event_type, entity_type, entity_id, actor_id,
    payload, schema_version, occurred_at
)
VALUES
    -- User registered
    (
        'eeeeeeee-0000-0000-0001-000000000001',
        'user.registered',
        'user',
        '11111111-0000-0000-0000-000000000001',
        NULL,
        '{"first_name": "Alice", "last_name": "Nguyen", "email": "alice.nguyen@example.com", "plan": "free"}'::JSONB,
        1,
        NOW() - INTERVAL '180 days'
    ),
    (
        'eeeeeeee-0000-0000-0001-000000000002',
        'user.registered',
        'user',
        '11111111-0000-0000-0000-000000000002',
        NULL,
        '{"first_name": "Bob", "last_name": "Kowalski", "email": "bob.kowalski@example.com", "plan": "pro"}'::JSONB,
        1,
        NOW() - INTERVAL '175 days'
    ),
    -- Subscription created (v1 writer: uses amount_cents)
    (
        'eeeeeeee-0000-0000-0001-000000000003',
        'subscription.created',
        'subscription',
        '22222222-0000-0000-0000-000000000001',
        '11111111-0000-0000-0000-000000000002',
        '{"plan": "pro", "amount_cents": 1999, "currency": "USD", "billing_cycle": "monthly"}'::JSONB,
        1,
        NOW() - INTERVAL '180 days'
    ),
    -- Invoice paid
    (
        'eeeeeeee-0000-0000-0001-000000000004',
        'invoice.paid',
        'invoice',
        '33333333-0000-0000-0000-000000000001',
        '11111111-0000-0000-0000-000000000002',
        '{"invoice_number": "INV-2024-0001", "amount_cents": 1999, "currency": "USD"}'::JSONB,
        1,
        NOW() - INTERVAL '170 days'
    ),
    -- User plan upgraded (v1)
    (
        'eeeeeeee-0000-0000-0001-000000000005',
        'user.plan_changed',
        'user',
        '11111111-0000-0000-0000-000000000003',
        '11111111-0000-0000-0000-000000000003',
        '{"old_plan": "pro", "new_plan": "enterprise", "first_name": "Carmen", "last_name": "Osei"}'::JSONB,
        1,
        NOW() - INTERVAL '90 days'
    ),
    -- User soft-deleted (v1)
    (
        'eeeeeeee-0000-0000-0001-000000000006',
        'user.deleted',
        'user',
        '11111111-0000-0000-0000-000000000008',
        '11111111-0000-0000-0000-000000000008',
        '{"first_name": "Hannah", "last_name": "Müller", "reason": "user_request"}'::JSONB,
        1,
        NOW() - INTERVAL '30 days'
    )
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------------
-- v2 Events (schema_version = 2, structured payload + metadata envelope)
-- ---------------------------------------------------------------------------

-- Use a shared correlation_id for the user-registration flow below
-- (all events from the same HTTP request share the same correlation_id)

INSERT INTO event_logs (
    id, event_type, entity_type, entity_id, actor_id,
    payload, schema_version, occurred_at,
    correlation_id, causation_id, source_service, metadata, aggregate_version
)
VALUES
    -- User registered (v2 writer: uses given_name/family_name in payload)
    (
        'eeeeeeee-0000-0000-0002-000000000001',
        'user.registered',
        'user',
        '11111111-0000-0000-0000-000000000006',
        NULL,
        '{
            "given_name":  "Fatima",
            "family_name": "Al-Rashid",
            "email":       "fatima.alrashid@example.com",
            "plan":        "pro"
        }'::JSONB,
        2,
        NOW() - INTERVAL '60 days',
        'cccccccc-0000-0000-0000-000000000001',  -- correlation_id
        NULL,                                     -- no causation (root event)
        'users',
        '{
            "request_id":    "req-aabb1122",
            "ip_address":    "203.0.113.50",
            "user_agent":    "Mozilla/5.0 (compatible; schema-evo-test)",
            "feature_flags": {"given_name_enabled": true}
        }'::JSONB,
        1
    ),
    -- Subscription created (v2 writer: uses amount decimal in payload)
    (
        'eeeeeeee-0000-0000-0002-000000000002',
        'subscription.created',
        'subscription',
        '22222222-0000-0000-0000-000000000004',
        '11111111-0000-0000-0000-000000000006',
        '{
            "plan":          "pro",
            "amount":        19.99,
            "amount_cents":  1999,
            "currency":      "USD",
            "billing_cycle": "monthly"
        }'::JSONB,
        2,
        NOW() - INTERVAL '60 days',
        'cccccccc-0000-0000-0000-000000000001',  -- same correlation as registration
        'eeeeeeee-0000-0000-0002-000000000001',  -- caused by user.registered
        'billing',
        '{
            "request_id":    "req-aabb1122",
            "ip_address":    "203.0.113.50",
            "user_agent":    "Mozilla/5.0 (compatible; schema-evo-test)",
            "feature_flags": {"amount_decimal_enabled": true}
        }'::JSONB,
        1
    ),
    -- Invoice paid (v2)
    (
        'eeeeeeee-0000-0000-0002-000000000003',
        'invoice.paid',
        'invoice',
        '33333333-0000-0000-0000-000000000003',
        '11111111-0000-0000-0000-000000000006',
        '{
            "invoice_number": "INV-2024-0003",
            "amount":         19.99,
            "amount_cents":   1999,
            "currency":       "USD"
        }'::JSONB,
        2,
        NOW() - INTERVAL '58 days',
        'cccccccc-0000-0000-0000-000000000002',
        'eeeeeeee-0000-0000-0002-000000000002',
        'billing',
        '{
            "request_id":    "req-ccdd3344",
            "ip_address":    "203.0.113.50",
            "user_agent":    "Stripe-Webhook/1.0",
            "feature_flags": {"amount_decimal_enabled": true}
        }'::JSONB,
        2
    ),
    -- User profile updated (v2: given_name/family_name in payload)
    (
        'eeeeeeee-0000-0000-0002-000000000004',
        'user.profile_updated',
        'user',
        '11111111-0000-0000-0000-000000000007',
        '11111111-0000-0000-0000-000000000007',
        '{
            "changed_fields": ["phone"],
            "given_name":     "George",
            "family_name":    "Tanaka",
            "phone":          "+81-3-5555-9999"
        }'::JSONB,
        2,
        NOW() - INTERVAL '14 days',
        'cccccccc-0000-0000-0000-000000000003',
        NULL,
        'users',
        '{
            "request_id":    "req-eeff5566",
            "ip_address":    "192.0.2.77",
            "user_agent":    "schema-evo-client/2.1.0",
            "feature_flags": {"given_name_enabled": true}
        }'::JSONB,
        3
    ),
    -- Subscription cancelled (v2)
    (
        'eeeeeeee-0000-0000-0002-000000000005',
        'subscription.cancelled',
        'subscription',
        '22222222-0000-0000-0000-000000000007',
        '11111111-0000-0000-0000-000000000009',
        '{
            "plan":          "pro",
            "amount":        19.99,
            "amount_cents":  1999,
            "currency":      "USD",
            "reason":        "payment_failure",
            "cancelled_at":  "2024-01-15T10:30:00Z"
        }'::JSONB,
        2,
        NOW() - INTERVAL '7 days',
        'cccccccc-0000-0000-0000-000000000004',
        NULL,
        'billing',
        '{
            "request_id":    "req-gghh7788",
            "ip_address":    "10.0.0.5",
            "user_agent":    "billing-worker/3.0.0",
            "feature_flags": {"amount_decimal_enabled": true}
        }'::JSONB,
        4
    ),
    -- User registered (new v2 user, Jing Wei)
    (
        'eeeeeeee-0000-0000-0002-000000000006',
        'user.registered',
        'user',
        '11111111-0000-0000-0000-000000000010',
        NULL,
        '{
            "given_name":  "Jing",
            "family_name": "Wei",
            "email":       "jing.wei@example.com",
            "plan":        "enterprise"
        }'::JSONB,
        2,
        NOW() - INTERVAL '30 days',
        'cccccccc-0000-0000-0000-000000000005',
        NULL,
        'users',
        '{
            "request_id":    "req-iijj9900",
            "ip_address":    "198.51.100.99",
            "user_agent":    "schema-evo-client/2.1.0",
            "feature_flags": {"given_name_enabled": true, "amount_decimal_enabled": true}
        }'::JSONB,
        1
    )
ON CONFLICT (id) DO NOTHING;
