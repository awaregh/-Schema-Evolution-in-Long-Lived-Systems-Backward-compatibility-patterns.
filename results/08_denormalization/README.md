# Scenario 8: Denormalization / Normalization Change

## Pattern: Dual-Write to Both Schemas + Eventual Consistency Window

Restructuring data layout — whether normalizing (splitting one table into many)
or denormalizing (collapsing related tables) — is among the most complex schema
evolution scenarios.  The dual-write pattern with an eventual-consistency
transition window is the only zero-downtime approach.

---

## Example: Normalize `users.address_*` into a separate `addresses` table

### Before

```sql
users (id, name, email, address_street, address_city, address_zip, address_country)
```

### After

```sql
users (id, name, email, primary_address_id REFERENCES addresses(id))
addresses (id, user_id, street, city, zip, country, is_primary)
```

---

## Phase 1: EXPAND — Create new table structure

```sql
CREATE TABLE addresses (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    street     TEXT,
    city       TEXT,
    zip        TEXT,
    country    TEXT NOT NULL DEFAULT 'US',
    is_primary BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX CONCURRENTLY idx_addresses_user_id ON addresses (user_id);

-- Add FK column to users (nullable during transition)
ALTER TABLE users ADD COLUMN primary_address_id BIGINT REFERENCES addresses(id);
```

---

## Phase 2: Dual-Write in Application Layer

```python
def update_user_address(user_id: int, addr: dict) -> None:
    # Write to NEW structure
    existing = db.fetchone(
        "SELECT id FROM addresses WHERE user_id=%s AND is_primary=TRUE", [user_id]
    )
    if existing:
        db.execute(
            """UPDATE addresses
                  SET street=:street, city=:city, zip=:zip, country=:country,
                      updated_at=NOW()
                WHERE id=:id""",
            {**addr, "id": existing["id"]},
        )
        address_id = existing["id"]
    else:
        address_id = db.fetchval(
            """INSERT INTO addresses (user_id, street, city, zip, country)
               VALUES (:user_id, :street, :city, :zip, :country)
               RETURNING id""",
            {"user_id": user_id, **addr},
        )
        db.execute(
            "UPDATE users SET primary_address_id=:aid WHERE id=:uid",
            {"aid": address_id, "uid": user_id},
        )

    # Also keep legacy columns current for v1 readers
    db.execute(
        """UPDATE users
              SET address_street=:street, address_city=:city,
                  address_zip=:zip, address_country=:country
            WHERE id=:user_id""",
        {**addr, "user_id": user_id},
    )
```

---

## Phase 3: BACKFILL — Migrate existing data

```sql
-- Insert addresses for users that don't have one yet
INSERT INTO addresses (user_id, street, city, zip, country)
SELECT id, address_street, address_city, address_zip,
       COALESCE(address_country, 'US')
  FROM users
 WHERE primary_address_id IS NULL
   AND address_street IS NOT NULL
 LIMIT 1000;

-- Back-fill the FK
UPDATE users u
   SET primary_address_id = a.id
  FROM addresses a
 WHERE a.user_id = u.id
   AND a.is_primary = TRUE
   AND u.primary_address_id IS NULL
 LIMIT 1000;
```

---

## Phase 4: Read from New Structure

```python
def get_user_address(user_id: int) -> dict | None:
    # Try new structure first
    row = db.fetchone(
        """SELECT a.street, a.city, a.zip, a.country
             FROM addresses a
             JOIN users u ON u.primary_address_id = a.id
            WHERE u.id = %s""",
        [user_id],
    )
    if row:
        return dict(row)

    # Fall back to legacy columns during transition window
    legacy = db.fetchone(
        "SELECT address_street, address_city, address_zip FROM users WHERE id=%s",
        [user_id],
    )
    return {
        "street": legacy["address_street"],
        "city":   legacy["address_city"],
        "zip":    legacy["address_zip"],
    } if legacy else None
```

---

## Phase 5: CONTRACT — Remove legacy columns

```sql
ALTER TABLE users
    DROP COLUMN address_street,
    DROP COLUMN address_city,
    DROP COLUMN address_zip,
    DROP COLUMN address_country;
```

---

## Safe vs Unsafe Comparison

### ❌ UNSAFE: Monolithic restructuring migration

```sql
BEGIN;
CREATE TABLE addresses (...);
INSERT INTO addresses SELECT ... FROM users;
ALTER TABLE users DROP COLUMN address_street, ...;
COMMIT;
-- Long transaction: full-table locks, no rollback path at application layer
```

### ✅ SAFE: Phased dual-write with eventual consistency (above)

---

## Expected Results

| Metric | Value |
|--------|-------|
| Downtime | 0 ms |
| Error rate during migration | 0 % |
| Backfill complexity | High (two-step: insert + FK update) |
| Rollback complexity | Low (pre-CONTRACT) / Very High (post-CONTRACT) |
| Operational risk | High — requires careful ordering and verification |
