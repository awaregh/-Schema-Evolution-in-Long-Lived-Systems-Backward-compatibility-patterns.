-- =============================================================================
-- Seed: 01_users.sql
-- Purpose: 10 sample users in v1 schema format (first_name / last_name).
--          given_name / family_name left NULL to simulate pre-backfill state.
-- Run after: 001_users_baseline.sql, 002_expand_given_name.sql
-- =============================================================================

INSERT INTO users (id, first_name, last_name, email, phone, status, plan, schema_version)
VALUES
    -- Active free-tier users (v1 data, not yet backfilled)
    (
        '11111111-0000-0000-0000-000000000001',
        'Alice',
        'Nguyen',
        'alice.nguyen@example.com',
        '+1-415-555-0101',
        'active',
        'free',
        1
    ),
    (
        '11111111-0000-0000-0000-000000000002',
        'Bob',
        'Kowalski',
        'bob.kowalski@example.com',
        '+1-312-555-0102',
        'active',
        'pro',
        1
    ),
    (
        '11111111-0000-0000-0000-000000000003',
        'Carmen',
        'Osei',
        'carmen.osei@example.com',
        NULL,
        'active',
        'enterprise',
        1
    ),
    (
        '11111111-0000-0000-0000-000000000004',
        'David',
        'Petrov',
        'david.petrov@example.com',
        '+44-20-5555-0104',
        'active',
        'free',
        1
    ),
    (
        '11111111-0000-0000-0000-000000000005',
        'Emeka',
        'Adeyemi',
        'emeka.adeyemi@example.com',
        '+234-800-555-0105',
        'active',
        'pro',
        1
    ),
    -- Users who have been backfilled (given_name / family_name populated, schema_version=2)
    (
        '11111111-0000-0000-0000-000000000006',
        'Fatima',
        'Al-Rashid',
        'fatima.alrashid@example.com',
        '+971-50-555-0106',
        'active',
        'pro',
        2
    ),
    (
        '11111111-0000-0000-0000-000000000007',
        'George',
        'Tanaka',
        'george.tanaka@example.com',
        '+81-3-5555-0107',
        'active',
        'enterprise',
        2
    ),
    -- Soft-deleted user (excluded from backfill)
    (
        '11111111-0000-0000-0000-000000000008',
        'Hannah',
        'Müller',
        'hannah.muller@example.com',
        '+49-30-5555-0108',
        'inactive',
        'free',
        1
    ),
    -- Suspended user
    (
        '11111111-0000-0000-0000-000000000009',
        'Ivan',
        'Sokolov',
        'ivan.sokolov@example.com',
        '+7-495-555-0109',
        'suspended',
        'pro',
        1
    ),
    -- User created by v2 application code (writes given_name directly)
    (
        '11111111-0000-0000-0000-000000000010',
        'Jing',
        'Wei',
        'jing.wei@example.com',
        '+86-10-5555-0110',
        'active',
        'enterprise',
        2
    )
ON CONFLICT (id) DO NOTHING;

-- Back-fill the shadow columns for users that were written by v2 writers
UPDATE users
SET    given_name  = first_name,
       family_name = last_name
WHERE  id IN (
    '11111111-0000-0000-0000-000000000006',
    '11111111-0000-0000-0000-000000000007',
    '11111111-0000-0000-0000-000000000010'
)
  AND  given_name IS NULL;

-- Soft-delete user 8 to simulate a deleted account
UPDATE users
SET    deleted_at = NOW() - INTERVAL '30 days'
WHERE  id = '11111111-0000-0000-0000-000000000008'
  AND  deleted_at IS NULL;
