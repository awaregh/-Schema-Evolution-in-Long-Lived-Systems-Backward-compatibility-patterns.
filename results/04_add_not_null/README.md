# Scenario 4: Add NOT NULL Column with Default

## Pattern: Multi-Step NOT NULL Addition

PostgreSQL rewrites the entire table when you add a `NOT NULL` column without a
server-side default (pre-PG11) or when the default is volatile.  The safe pattern
splits this into three phases that never acquire a prolonged lock.

---

## Phase 1: Add nullable column with default

```sql
-- Fast: metadata-only in PG11+ for constant defaults
ALTER TABLE users
  ADD COLUMN locale TEXT NOT NULL DEFAULT 'en-US';
```

> **PostgreSQL 11+:** Adding a column with a `NOT NULL` constant default is
> instant (stored as table metadata; no row rewrite).  For older versions or
> non-constant defaults, use the steps below.

### Pre-PG11 / volatile default workaround

```sql
-- Step 1: add nullable column
ALTER TABLE users ADD COLUMN locale TEXT;

-- Step 2: set server-side default for new inserts
ALTER TABLE users ALTER COLUMN locale SET DEFAULT 'en-US';
```

---

## Phase 2: BACKFILL existing rows

```sql
UPDATE users
   SET locale = 'en-US'
 WHERE locale IS NULL
 LIMIT 1000;
```

Verify:

```sql
SELECT COUNT(*) FROM users WHERE locale IS NULL;
-- Expected: 0
```

---

## Phase 3: Add NOT NULL constraint

```sql
-- In PostgreSQL 12+ this is validated without rewriting the table
-- if you first add it as NOT VALID, then validate separately
ALTER TABLE users
  ADD CONSTRAINT users_locale_not_null CHECK (locale IS NOT NULL) NOT VALID;

-- Validate without holding a full-table lock
ALTER TABLE users VALIDATE CONSTRAINT users_locale_not_null;

-- Optional: convert to native NOT NULL (requires brief lock, but no rewrite)
ALTER TABLE users ALTER COLUMN locale SET NOT NULL;
ALTER TABLE users DROP CONSTRAINT users_locale_not_null;
```

---

## Safe vs Unsafe Comparison

### ❌ UNSAFE: Single statement on large table (pre-PG11)

```sql
-- Rewrites entire table; holds ACCESS EXCLUSIVE lock for minutes/hours
ALTER TABLE users ADD COLUMN locale TEXT NOT NULL DEFAULT 'en-US';
```

### ✅ SAFE: Phased approach (above)

- Phase 1 is instant.
- Phase 2 runs in small batches.
- Phase 3 validation is a share-lock operation.

---

## Application Changes

```python
def create_user(data: dict) -> None:
    locale = data.get("locale", "en-US")  # default applied in app layer too
    db.execute(
        "INSERT INTO users (name, email, locale) VALUES (:name, :email, :locale)",
        {"name": data["name"], "email": data["email"], "locale": locale},
    )
```

---

## Expected Results

| Metric | Value |
|--------|-------|
| Downtime | 0 ms |
| Error rate during migration | 0 % |
| Lock duration (Phase 3 validate) | Milliseconds |
| Rollback complexity | Low |
| Operational risk | Low |
