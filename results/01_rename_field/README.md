# Scenario 1: Rename Field (first_name → given_name)

## Pattern: Expand / Contract with Dual-Write

Renaming a column is one of the most common and most dangerous schema changes.
A direct `ALTER TABLE … RENAME COLUMN` immediately breaks every live query that
references the old name.  The Expand/Contract pattern eliminates this risk by
introducing the new name alongside the old one and migrating data gradually.

---

## Phase 1: EXPAND

Add the new column without removing the old one, so both names coexist.

```sql
-- Non-blocking: PostgreSQL adds the nullable column instantly
ALTER TABLE users ADD COLUMN given_name TEXT;

-- Build the index in the background to avoid a full-table lock
CREATE INDEX CONCURRENTLY idx_users_given_name ON users (given_name);
```

**Application change (dual-write):**

```python
def update_user(user_id: int, data: dict) -> None:
    # Write to BOTH columns so rollback is always possible
    db.execute(
        """UPDATE users
              SET first_name = :name,
                  given_name = :name
            WHERE id = :id""",
        {"name": data["first_name"], "id": user_id},
    )
```

**Read logic (prefer new, fall back to old):**

```python
def get_display_name(row: dict) -> str:
    return row.get("given_name") or row.get("first_name", "")
```

---

## Phase 2: BACKFILL

Migrate historical rows that were written before dual-write was deployed.
Batch the update to avoid long locks and replication lag.

```sql
-- Repeat until rowcount = 0
UPDATE users
   SET given_name = first_name
 WHERE given_name IS NULL
 LIMIT 1000;
```

Monitor progress:

```bash
python analysis/measure_column_reads.py \
    --scenario 01_rename_field \
    --table users \
    --old-column first_name \
    --new-column given_name \
    --interval 30 \
    --duration 600
```

Verify completion:

```sql
SELECT COUNT(*) FROM users WHERE given_name IS NULL;
-- Expected: 0
```

---

## Phase 3: CONTRACT

Once **all** consumers have been updated to use `given_name`, remove the legacy
column.

**Application change:** remove every reference to `first_name`.

```sql
-- Safe to run only after all app instances are on the new code
ALTER TABLE users DROP COLUMN first_name;
DROP INDEX IF EXISTS idx_users_first_name;
```

---

## Safe vs Unsafe Comparison

### ❌ UNSAFE: Direct rename

```sql
ALTER TABLE users RENAME COLUMN first_name TO given_name;
```

- Acquires an `ACCESS EXCLUSIVE` lock for the duration of the statement.
- Immediately breaks all live queries referencing `first_name` — including
  running application instances and read replicas.
- No rollback path without another rename (which also locks).

### ✅ SAFE: Expand / Contract (above)

- Each phase is independently deployable and reversible.
- Zero downtime: old and new code run simultaneously without errors.
- Rollback is simply stopping dual-write and dropping the new column.

---

## Rollback Procedures

| Phase | Rollback Action |
|-------|----------------|
| After EXPAND | `ALTER TABLE users DROP COLUMN given_name;` |
| During BACKFILL | Stop backfill job; drop `given_name` |
| After CONTRACT | Restore from backup or replay WAL (non-trivial) |

> **Best practice:** never proceed to CONTRACT until you have confirmed that no
> running code references `first_name`.

---

## Expected Results

| Metric | Value |
|--------|-------|
| Downtime | 0 ms |
| Error rate during migration | 0 % |
| Backfill time (10k rows) | ~2 s |
| Backfill time (1M rows, batched) | ~3–4 min |
| Rollback complexity | Low (drop column) |
| Operational risk | Low |
