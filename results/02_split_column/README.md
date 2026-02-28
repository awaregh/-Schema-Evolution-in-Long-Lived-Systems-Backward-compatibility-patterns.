# Scenario 2: Split Column (name → first_name + last_name)

## Pattern: Expand / Contract with Computed Columns

Splitting a single `name` TEXT column into `first_name` and `last_name` is
structurally similar to a rename but requires a data-transformation step during
backfill.  The key insight: old consumers see `name`; new consumers see the pair.

---

## Phase 1: EXPAND

```sql
ALTER TABLE users ADD COLUMN first_name TEXT;
ALTER TABLE users ADD COLUMN last_name  TEXT;

CREATE INDEX CONCURRENTLY idx_users_first_name ON users (first_name);
CREATE INDEX CONCURRENTLY idx_users_last_name  ON users (last_name);
```

**Application dual-write (write to all three columns):**

```python
def create_user(data: dict) -> None:
    first = data.get("first_name", "")
    last  = data.get("last_name", "")
    full  = data.get("name") or f"{first} {last}".strip()
    db.execute(
        """INSERT INTO users (name, first_name, last_name, email)
           VALUES (:name, :first, :last, :email)""",
        {"name": full, "first": first, "last": last, "email": data["email"]},
    )
```

**Read logic (new fields preferred):**

```python
def get_user_name(row: dict) -> tuple[str, str]:
    if row.get("first_name"):
        return row["first_name"], row.get("last_name", "")
    # Best-effort split of legacy full name
    parts = (row.get("name") or "").split(" ", 1)
    return parts[0], parts[1] if len(parts) > 1 else ""
```

---

## Phase 2: BACKFILL

```sql
-- Split on first space; adjust regex for your data quality needs
UPDATE users
   SET first_name = split_part(name, ' ', 1),
       last_name  = NULLIF(substring(name FROM position(' ' IN name) + 1), '')
 WHERE first_name IS NULL
   AND name IS NOT NULL
 LIMIT 1000;
```

Validate data quality after backfill:

```sql
SELECT COUNT(*) FROM users WHERE first_name IS NULL AND name IS NOT NULL;
-- Expected: 0

-- Spot-check round-trip consistency
SELECT name,
       first_name || ' ' || COALESCE(last_name, '') AS reconstructed
  FROM users
 LIMIT 20;
```

---

## Phase 3: CONTRACT

```sql
ALTER TABLE users DROP COLUMN name;
```

---

## Safe vs Unsafe Comparison

### ❌ UNSAFE: Single destructive migration

```sql
ALTER TABLE users ADD COLUMN first_name TEXT;
ALTER TABLE users ADD COLUMN last_name  TEXT;
UPDATE users SET first_name = split_part(name,' ',1),
                 last_name  = substring(name FROM position(' ' IN name)+1);
ALTER TABLE users DROP COLUMN name;   -- immediately breaks v1 consumers
```

### ✅ SAFE: Phased expansion with dual-write (described above)

---

## Rollback Procedures

| Phase | Rollback Action |
|-------|----------------|
| After EXPAND | `ALTER TABLE users DROP COLUMN first_name, DROP COLUMN last_name;` |
| During BACKFILL | Stop backfill; drop new columns |
| After CONTRACT | Restore `name` via `first_name \|\| ' ' \|\| last_name` migration |

---

## Expected Results

| Metric | Value |
|--------|-------|
| Downtime | 0 ms |
| Error rate during migration | 0 % |
| Data fidelity risk | Low–Medium (name splitting heuristics) |
| Rollback complexity | Low (pre-CONTRACT) / High (post-CONTRACT) |
