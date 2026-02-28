# Scenario 3: Type Change (amount_cents INTEGER → amount DECIMAL)

## Pattern: Shadow Column + Dual-Read/Write

Changing a column's data type (especially widening from integer cents to decimal
dollars) requires a new column, a conversion formula, and careful handling of
precision during the transition window.

---

## Phase 1: EXPAND — Add shadow column

```sql
-- Add new column alongside the original
ALTER TABLE orders ADD COLUMN amount NUMERIC(12, 2);

CREATE INDEX CONCURRENTLY idx_orders_amount ON orders (amount);
```

**Application dual-write with unit conversion:**

```python
def create_order(data: dict) -> None:
    amount_cents = data.get("amount_cents")
    amount_decimal = data.get("amount")

    # Derive whichever value is missing
    if amount_cents is None and amount_decimal is not None:
        amount_cents = int(round(float(amount_decimal) * 100))
    if amount_decimal is None and amount_cents is not None:
        amount_decimal = Decimal(amount_cents) / 100

    db.execute(
        """INSERT INTO orders (amount_cents, amount, ...)
           VALUES (:cents, :decimal, ...)""",
        {"cents": amount_cents, "decimal": amount_decimal, ...},
    )
```

---

## Phase 2: BACKFILL

```sql
UPDATE orders
   SET amount = ROUND(amount_cents::NUMERIC / 100, 2)
 WHERE amount IS NULL
   AND amount_cents IS NOT NULL
 LIMIT 1000;
```

**Precision validation:**

```sql
-- Verify no rounding drift beyond 1 cent
SELECT COUNT(*)
  FROM orders
 WHERE ABS(amount - (amount_cents::NUMERIC / 100)) > 0.01;
-- Expected: 0
```

---

## Phase 3: CONTRACT

```sql
-- Only after all application code reads from `amount`
ALTER TABLE orders DROP COLUMN amount_cents;
```

---

## Safe vs Unsafe Comparison

### ❌ UNSAFE: In-place type alteration

```sql
-- Rewrites every row; holds ACCESS EXCLUSIVE lock for entire duration
ALTER TABLE orders ALTER COLUMN amount_cents TYPE NUMERIC(12,2)
  USING amount_cents::NUMERIC / 100;
```

### ✅ SAFE: Shadow column with backfill (above)

---

## Edge Cases

- **Currency rounding:** always use `ROUND(..., 2)` in backfill SQL; never rely on
  floating-point arithmetic.
- **Concurrent writes during backfill:** dual-write ensures no row is left behind.
- **Reporting queries:** update BI queries to use `amount` before CONTRACT phase.

---

## Expected Results

| Metric | Value |
|--------|-------|
| Downtime | 0 ms |
| Error rate during migration | 0 % |
| Precision errors | 0 (with ROUND) |
| Rollback complexity | Low (pre-CONTRACT) |
| Operational risk | Medium (unit conversion bugs possible) |
