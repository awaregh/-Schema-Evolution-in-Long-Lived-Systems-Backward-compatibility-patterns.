# Scenario 5: Remove Field (with Deprecation Strategy)

## Pattern: Deprecate → Ignore → Remove

Column removal is the reverse of expansion.  The key risk is removing a column
that an old application version is still SELECT-ing or INSERT-ing into.  A
structured deprecation window eliminates this risk.

---

## Deprecation Timeline

```
Week 0:   Mark column deprecated in schema comments + API docs
Week 1:   Application stops writing to the column (but still reads)
Week 2:   Application stops reading from the column
Week 4:   Verify zero references in application code + queries
Week 5:   Drop the column
```

---

## Phase 1: Mark as Deprecated

```sql
COMMENT ON COLUMN users.legacy_notes IS
  'DEPRECATED 2024-01-15: Use the user_notes table instead. Will be removed 2024-02-19.';
```

Emit deprecation warnings in application code:

```python
import warnings

def get_user(user_id: int) -> dict:
    row = db.fetchone("SELECT * FROM users WHERE id = %s", [user_id])
    if row.get("legacy_notes"):
        warnings.warn(
            "users.legacy_notes is deprecated and will be removed 2024-02-19. "
            "Use user_notes table.",
            DeprecationWarning,
            stacklevel=2,
        )
    return row
```

---

## Phase 2: Stop Writing

```python
def update_user(user_id: int, data: dict) -> None:
    # No longer include legacy_notes in the UPDATE
    db.execute(
        "UPDATE users SET name=:name, email=:email WHERE id=:id",
        {"name": data["name"], "email": data["email"], "id": user_id},
    )
    # Writes now go to user_notes table
    if "notes" in data:
        upsert_user_notes(user_id, data["notes"])
```

---

## Phase 3: Stop Reading

```python
def get_user(user_id: int) -> dict:
    # No longer SELECT legacy_notes
    row = db.fetchone(
        "SELECT id, name, email FROM users WHERE id = %s",
        [user_id],
    )
    return row
```

---

## Phase 4: Audit & Remove

**Before dropping, confirm zero live references:**

```bash
# Scan application codebase
grep -r "legacy_notes" services/ --include="*.py"
# Expected: 0 matches (only migration files)

# Check pg_stat_statements for recent queries touching the column
SELECT query, calls, last_call
  FROM pg_stat_statements
 WHERE query ILIKE '%legacy_notes%'
   AND last_call > NOW() - INTERVAL '7 days';
-- Expected: 0 rows
```

**Drop the column:**

```sql
-- Instant metadata-only operation (no row rewrite)
ALTER TABLE users DROP COLUMN legacy_notes;
```

---

## Safe vs Unsafe Comparison

### ❌ UNSAFE: Immediate removal

```sql
ALTER TABLE users DROP COLUMN legacy_notes;
-- Any running app instance referencing legacy_notes gets:
-- ERROR: column "legacy_notes" does not exist
```

### ✅ SAFE: Phased deprecation (above)

---

## Consumer Contract Tests

```python
# tests/contract/test_user_api.py
def test_user_response_does_not_contain_deprecated_field():
    resp = client.get("/users/1")
    assert "legacy_notes" not in resp.json(), \
        "legacy_notes should have been removed from the API response"
```

---

## Expected Results

| Metric | Value |
|--------|-------|
| Downtime | 0 ms |
| Error rate during removal | 0 % |
| Required deprecation window | ≥ 2 deployment cycles |
| Rollback complexity | High (post-DROP) / None (pre-DROP) |
| Operational risk | Low (if deprecation window is respected) |
