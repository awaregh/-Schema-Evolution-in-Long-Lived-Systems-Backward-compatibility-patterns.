-- =============================================================================
-- Migration: 006_expand_amount_decimal
-- Scenario 3: Change column type INTEGER → NUMERIC  (EXPAND phase)
-- Pattern:    Expand / Contract  (type-change variant)
-- Safety:     SAFE – adds a new nullable column alongside amount_cents.
--             v1 application code: reads/writes amount_cents only.
--             v2 application code: reads amount; dual-writes both columns.
--             The backfill worker populates amount from amount_cents for
--             pre-existing rows (see migration 003 pattern / backfill_amount job).
-- Prerequisite: 005_subscriptions_baseline
-- =============================================================================

-- -----------------------------------------------------------------------------
-- UP
-- -----------------------------------------------------------------------------

-- subscriptions: add decimal shadow column
ALTER TABLE subscriptions
    ADD COLUMN IF NOT EXISTS amount NUMERIC(10, 2);

COMMENT ON COLUMN subscriptions.amount IS
    'v2 decimal monetary column (amount_cents / 100.0). NULL until backfilled.';

-- invoices: same shadow column
ALTER TABLE invoices
    ADD COLUMN IF NOT EXISTS amount NUMERIC(10, 2);

COMMENT ON COLUMN invoices.amount IS
    'v2 decimal monetary column (amount_cents / 100.0). NULL until backfilled.';

-- Partial indexes: cover only backfilled rows so the index is immediately useful
-- and grows incrementally as the backfill worker processes batches.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_subscriptions_amount
    ON subscriptions (amount)
    WHERE amount IS NOT NULL;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_invoices_amount
    ON invoices (amount)
    WHERE amount IS NOT NULL;

-- Trigger function: keep amount_cents and amount in sync for new writes
-- so that v1 readers always see a consistent integer value.
CREATE OR REPLACE FUNCTION sync_amount_cents()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.amount IS NOT NULL AND NEW.amount_cents IS NOT DISTINCT FROM OLD.amount_cents THEN
        -- v2 writer updated amount only; derive amount_cents
        NEW.amount_cents := ROUND(NEW.amount * 100)::INTEGER;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_subscriptions_sync_amount_cents
    BEFORE INSERT OR UPDATE ON subscriptions
    FOR EACH ROW EXECUTE FUNCTION sync_amount_cents();

CREATE TRIGGER trg_invoices_sync_amount_cents
    BEFORE INSERT OR UPDATE ON invoices
    FOR EACH ROW EXECUTE FUNCTION sync_amount_cents();

-- -----------------------------------------------------------------------------
-- DOWN
-- -----------------------------------------------------------------------------
-- DROP TRIGGER IF EXISTS trg_invoices_sync_amount_cents      ON invoices;
-- DROP TRIGGER IF EXISTS trg_subscriptions_sync_amount_cents ON subscriptions;
-- DROP FUNCTION IF EXISTS sync_amount_cents();
-- DROP INDEX CONCURRENTLY IF EXISTS idx_invoices_amount;
-- DROP INDEX CONCURRENTLY IF EXISTS idx_subscriptions_amount;
-- ALTER TABLE invoices      DROP COLUMN IF EXISTS amount;
-- ALTER TABLE subscriptions DROP COLUMN IF EXISTS amount;
