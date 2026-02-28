# Schema Evolution Anti-Patterns

A catalogue of dangerous schema migration practices, why they cause production
incidents, and the safe alternatives.

---

## AP-1: Renaming Columns Directly

### Description

```sql
ALTER TABLE users RENAME COLUMN first_name TO given_name;
```

### Why It Breaks

PostgreSQL executes `RENAME COLUMN` with an `ACCESS EXCLUSIVE` lock.  Every
concurrent `SELECT`, `INSERT`, `UPDATE`, or `DELETE` on the table is blocked for
the lock duration.  More critically, **all live application instances referencing
the old column name immediately get errors**:

```
ERROR:  column "first_name" does not exist
```

A rolling deployment means some pods run old code for 5–15 minutes.  Those pods
crash on every database call.

### Real Example

In 2020 a major SaaS company renamed a `name` column to `full_name` with a
direct RENAME, causing a 12-minute outage for all write operations while the
old pods were still running.

### Safe Alternative

Use **Expand/Contract with dual-write** (see `results/01_rename_field/README.md`):

1. `ALTER TABLE users ADD COLUMN given_name TEXT;`
2. Deploy dual-write code.
3. Backfill: `UPDATE users SET given_name=first_name WHERE given_name IS NULL LIMIT 1000;`
4. Switch all reads to `given_name`.
5. `ALTER TABLE users DROP COLUMN first_name;`

---

## AP-2: Adding NOT NULL Without a Default

### Description

```sql
ALTER TABLE users ADD COLUMN locale TEXT NOT NULL;
```

### Why It Breaks

On PostgreSQL < 11, this rewrites the entire table synchronously while holding
an `ACCESS EXCLUSIVE` lock.  On a 100 GB table this takes **tens of minutes**.
All reads and writes to the table are blocked for the entire duration.

Even on PG11+, if the default is volatile (e.g., `DEFAULT gen_random_uuid()`)
the table is still rewritten.

### Real Example

A 50 M-row table migration without a default caused an 18-minute full outage.
`pg_locks` showed 2 000+ blocked queries.

### Safe Alternative

```sql
-- Step 1: nullable column (instant)
ALTER TABLE users ADD COLUMN locale TEXT;

-- Step 2: set default for future inserts
ALTER TABLE users ALTER COLUMN locale SET DEFAULT 'en-US';

-- Step 3: backfill in batches
UPDATE users SET locale='en-US' WHERE locale IS NULL LIMIT 1000;

-- Step 4: add NOT VALID constraint (no rewrite)
ALTER TABLE users ADD CONSTRAINT chk_locale_not_null
  CHECK (locale IS NOT NULL) NOT VALID;

-- Step 5: validate (ShareUpdateExclusive lock only)
ALTER TABLE users VALIDATE CONSTRAINT chk_locale_not_null;
```

---

## AP-3: Removing Columns Without a Deprecation Window

### Description

```sql
ALTER TABLE users DROP COLUMN legacy_notes;
```

…deployed immediately, without removing application references first.

### Why It Breaks

Any `SELECT *` query returns a different set of columns.  Any query explicitly
naming `legacy_notes` errors immediately.  ORM models that auto-map columns will
get unexpected errors or silent data loss.

### Real Example

A microservice was removed from one squad's roadmap.  The column was dropped in
the same sprint.  A third-party integration that the team didn't know about was
still reading the column — the integration silently started receiving empty
responses.

### Safe Alternative

Follow the **Deprecate → Ignore → Remove** pattern (Scenario 5):

1. Add `COMMENT ON COLUMN` and emit `DeprecationWarning` in application code.
2. Stop writing to the column.
3. Stop reading from the column.
4. Wait ≥ 2 full deployment cycles.
5. Audit `pg_stat_statements` for recent queries.
6. Drop the column.

---

## AP-4: Breaking API Contract Changes

### Description

Changing a response field name, type, or required status in a REST or gRPC API
without versioning:

```python
# Before
return {"first_name": user.first_name}

# After — same endpoint, no version bump
return {"given_name": user.given_name}
```

### Why It Breaks

Clients that expected `first_name` now get `None` / `KeyError`.  Mobile clients
cannot update instantly — an old app version may run for months.

### Real Example

A fintech company changed `amount` from a string `"12.50"` to an integer `1250`
(cents) without versioning.  Mobile apps crashed for 15% of users until a forced
app update was pushed — which took 3 days.

### Safe Alternative

- Version your API: `/v1/users` and `/v2/users`.
- Use content negotiation: `Accept: application/vnd.api.v2+json`.
- Add new fields alongside old ones; never remove until old clients are gone.
- Use `X-API-Version` header for read-time migration (Scenario 7).

---

## AP-5: Single Migration That Does Expand + Contract Together

### Description

```sql
BEGIN;
ALTER TABLE users ADD COLUMN given_name TEXT;
UPDATE users SET given_name = first_name;
ALTER TABLE users DROP COLUMN first_name;
COMMIT;
```

### Why It Breaks

This is a **long-running transaction** that holds an `ACCESS EXCLUSIVE` lock
for its entire duration.  The `UPDATE` iterates every row while the lock is held,
blocking all reads and writes.  If the transaction fails mid-way, a partial
migration cannot be rolled back cleanly.

### Real Example

A developer combined expand + backfill + contract into one Alembic migration.
On a table with 8 M rows the transaction held a lock for 4 minutes, causing a
4-minute outage.

### Safe Alternative

**Never combine EXPAND and CONTRACT in the same deployment.**  Separate them by
at least one deployment cycle.  Use separate Alembic migration files with
explicit `--autogenerate` steps.

---

## AP-6: Missing Rollback Strategy

### Description

Deploying a migration with no documented or tested rollback path:

```
Migration: ALTER TABLE orders ALTER COLUMN amount TYPE NUMERIC(12,2) USING ...
Rollback: ???
```

### Why It Breaks

When an incident occurs mid-migration, the team has no pre-tested path to
restore service.  Improvised rollbacks under pressure are error-prone and often
make things worse.

### Safe Alternative

For every migration, document:

```markdown
## Rollback Steps
1. `ALTER TABLE orders ADD COLUMN amount_cents INT;` (if not present)
2. `UPDATE orders SET amount_cents = (amount * 100)::INT WHERE amount_cents IS NULL;`
3. Redeploy v1 application code.
4. Drop amount column.
```

Test rollback in staging **before** executing the forward migration in
production.

---

## AP-7: No Consumer Contract Tests

### Description

Deploying a schema change without automated tests that verify API/event
consumers still receive expected shapes.

### Why It Breaks

Without contract tests, breaking changes are discovered in production by
customer-facing errors, not in CI.

### Real Example

A team removed a `metadata` field from Kafka events.  Six downstream consumers
(owned by four different teams) started failing.  The issue was discovered
through support tickets 2 hours later.

### Safe Alternative

Use **Consumer-Driven Contract Testing** (e.g., Pact):

```python
# tests/contract/test_user_event_consumer.py
from pact import Consumer, Provider

pact = Consumer("order-service").has_pact_with(Provider("user-service"))

def test_user_created_event_contract():
    expected = {
        "user_id": 42,
        "given_name": "Alice",
        "email": "alice@example.com",
    }
    pact.given("user 42 exists").upon_receiving(
        "a user.created event"
    ).with_request(...).will_respond_with(200, body=expected)
```

Run contract tests in CI on every PR that touches event schemas.

---

## AP-8: Monolithic Migrations (Doing Too Much at Once)

### Description

One migration file that:
- Adds 3 columns
- Renames 2 columns
- Adds 4 indexes
- Modifies 2 foreign keys
- Backfills 10 M rows

### Why It Breaks

- Any failure requires rolling back everything.
- Lock contention from multiple simultaneous operations.
- Impossible to isolate the cause of performance degradation.
- Long transaction window increases replication lag.

### Safe Alternative

**One logical change per migration file.**  If you need to add 3 columns, create
3 migration files (or at minimum 3 distinct `ALTER TABLE` statements that each
commit independently).

```
migrations/
  0042_add_users_given_name.sql
  0043_backfill_users_given_name.sql  (separate job, not a migration)
  0044_drop_users_first_name.sql
```

---

## AP-9: Lock-Prone Operations Without CONCURRENTLY

### Description

```sql
-- Holds ACCESS EXCLUSIVE lock for the duration of the index build
CREATE INDEX idx_users_email ON users (email);
```

On a large table this blocks all reads and writes while the index is built.

### Why It Breaks

Index builds on large tables (> 10 M rows) can take 10–60 minutes.  Without
`CONCURRENTLY`, every query on the table queues behind the lock.

### Real Example

An engineer added a routine index to a 40 M-row table during business hours.
The build took 22 minutes.  All API endpoints serving that table returned 504s.

### Safe Alternative

```sql
-- Allows reads and writes to continue during index build
CREATE INDEX CONCURRENTLY idx_users_email ON users (email);
```

Monitor progress:

```sql
SELECT phase, blocks_done, blocks_total
  FROM pg_stat_progress_create_index
 WHERE relid = 'users'::regclass;
```

Note: `CONCURRENTLY` cannot run inside a transaction block; run it as a
standalone statement.

---

## AP-10: Ignoring schema_version Field in Events

### Description

Publishing events without a `schema_version` field:

```json
{"event": "user.created", "user_id": 42, "first_name": "Alice"}
```

### Why It Breaks

When the schema changes, consumers cannot distinguish old-format from new-format
events.  Events in Kafka may replay for days (retention window).  Without
versioning, a consumer cannot deserialize old events after a schema change.

### Real Example

A consumer crashed when replaying 3 days of Kafka history after a field rename,
because it could not tell which events had the old vs new field name.  Manual
re-processing was required.

### Safe Alternative

Always include `schema_version` (integer, starts at 1):

```json
{
  "event": "user.created",
  "schema_version": 2,
  "user_id": 42,
  "given_name": "Alice"
}
```

Consumer handles both versions:

```python
def handle_user_created(event: dict) -> None:
    version = event.get("schema_version", 1)
    if version == 1:
        name = event.get("first_name", "")
    else:
        name = event.get("given_name", "")
    process(event["user_id"], name)
```
