# Schema Evolution Playbook

A step-by-step operations runbook for zero-downtime schema migrations in
production PostgreSQL services.  Follow each phase in sequence; never skip ahead.

---

## Table of Contents

1. [Pre-Migration Checklist](#1-pre-migration-checklist)
2. [Expand Phase Runbook](#2-expand-phase-runbook)
3. [Backfill Runbook](#3-backfill-runbook)
4. [Contract Phase Runbook](#4-contract-phase-runbook)
5. [Rollback Procedures](#5-rollback-procedures)
6. [Feature Flag Management](#6-feature-flag-management)
7. [Decision Tree: Which Pattern to Use](#7-decision-tree-which-pattern-to-use)
8. [Communication Plan](#8-communication-plan)

---

## 1. Pre-Migration Checklist

Complete every item before deploying any schema change.

### Database Health

- [ ] Replication lag < 10 s on all replicas (`SELECT * FROM pg_stat_replication`)
- [ ] No long-running transactions > 30 s (`SELECT * FROM pg_stat_activity WHERE state='active' AND now()-query_start > '30s'`)
- [ ] Autovacuum is not running on the target table (`SELECT * FROM pg_stat_user_tables WHERE relname='<table>'`)
- [ ] Table size noted: `SELECT pg_size_pretty(pg_total_relation_size('<table>'))`
- [ ] Disk space > 2× table size available (for index builds)

### Application

- [ ] Feature flags prepared and tested in staging
- [ ] Dual-write code deployed and verified in staging
- [ ] Old code can still run against new schema (forward compatibility check)
- [ ] Rollback code path tested in staging

### Observability

- [ ] Error rate dashboards open and alerting thresholds confirmed
- [ ] p95 latency baseline recorded
- [ ] Backfill progress query prepared (see §3)
- [ ] On-call engineer notified

### Approvals

- [ ] Migration reviewed by a second engineer
- [ ] Change window scheduled (off-peak hours preferred)
- [ ] Stakeholders notified per §8

---

## 2. Expand Phase Runbook

The Expand phase adds new schema elements without removing anything.

### Step 2.1 – Add new column (nullable)

```sql
-- Always nullable initially; never add NOT NULL without a default in one step
ALTER TABLE users ADD COLUMN given_name TEXT;
```

Expected: instant (`< 1 ms`).  No lock contention.

**Verify:**

```sql
SELECT column_name, data_type, is_nullable
  FROM information_schema.columns
 WHERE table_name='users' AND column_name='given_name';
```

### Step 2.2 – Create index concurrently

```sql
-- CONCURRENTLY avoids an exclusive lock; runs in background
CREATE INDEX CONCURRENTLY idx_users_given_name ON users (given_name);
```

Monitor progress:

```sql
SELECT phase, blocks_done, blocks_total,
       ROUND(100.0 * blocks_done / NULLIF(blocks_total, 0), 1) AS pct
  FROM pg_stat_progress_create_index
 WHERE relid = 'users'::regclass;
```

### Step 2.3 – Deploy dual-write application code

```python
def save_user(conn, user_id: int, data: dict) -> None:
    name = data.get("given_name") or data.get("first_name", "")
    conn.execute(
        """UPDATE users
              SET first_name = :name,   -- keep old column for v1
                  given_name = :name    -- populate new column for v2
            WHERE id = :id""",
        {"name": name, "id": user_id},
    )
```

**Canary deploy first (5% traffic).** Monitor error rate for 5 minutes before
promoting to 100%.

### Step 2.4 – Verify dual-write is live

```sql
-- Sample of recently written rows should show BOTH columns populated
SELECT id, first_name, given_name, updated_at
  FROM users
 ORDER BY updated_at DESC
 LIMIT 10;
```

---

## 3. Backfill Runbook

Backfill migrates rows written before dual-write was deployed.

### Step 3.1 – Estimate scope

```sql
SELECT
    COUNT(*) FILTER (WHERE given_name IS NULL) AS to_migrate,
    COUNT(*) AS total,
    ROUND(100.0 * COUNT(*) FILTER (WHERE given_name IS NULL) / COUNT(*), 1) AS pct_remaining
  FROM users;
```

### Step 3.2 – Run batched backfill

Use batch size 1000 to balance throughput vs. lock contention.

```bash
python analysis/measure_migration_time.py \
    --scenario 01_rename_field \
    --sql "UPDATE users SET given_name=first_name WHERE given_name IS NULL" \
    --batch-size 1000
```

Or run directly in psql with a loop:

```sql
DO $$
DECLARE updated INT;
BEGIN
  LOOP
    UPDATE users SET given_name = first_name
     WHERE id IN (
         SELECT id FROM users WHERE given_name IS NULL LIMIT 1000
     );
    GET DIAGNOSTICS updated = ROW_COUNT;
    EXIT WHEN updated = 0;
    PERFORM pg_sleep(0.1);  -- brief pause to reduce I/O pressure
  END LOOP;
END $$;
```

### Step 3.3 – Monitor progress

```bash
python analysis/measure_column_reads.py \
    --scenario 01_rename_field \
    --table users \
    --new-column given_name \
    --interval 30 \
    --duration 3600
```

### Step 3.4 – Verify completion

```sql
SELECT COUNT(*) FROM users WHERE given_name IS NULL;
-- Must be 0 before proceeding to CONTRACT
```

### Step 3.5 – Backfill health checks

During backfill, confirm:

```sql
-- No replication lag spike
SELECT client_addr, write_lag, flush_lag, replay_lag
  FROM pg_stat_replication;

-- No lock waits piling up
SELECT COUNT(*) FROM pg_locks WHERE granted = FALSE;

-- Query time not elevated
SELECT mean_exec_time, calls
  FROM pg_stat_statements
 WHERE query ILIKE '%UPDATE users%given_name%'
 ORDER BY mean_exec_time DESC
 LIMIT 5;
```

---

## 4. Contract Phase Runbook

Remove the legacy column only after **all** of the following are true:

- [ ] Backfill complete (0 rows with `given_name IS NULL`)
- [ ] 100% of application instances running code that reads `given_name`
- [ ] Zero references to `first_name` in application codebase (`grep -r first_name services/`)
- [ ] Contract tests passing (see §7 in `anti_patterns.md`)
- [ ] Observation window of ≥ 48 hours since dual-write cutover with 0 errors

### Step 4.1 – Drop old column

```sql
-- Instant: marks column dead; space reclaimed by next VACUUM
ALTER TABLE users DROP COLUMN first_name;
```

### Step 4.2 – Drop orphaned indexes

```sql
DROP INDEX IF EXISTS idx_users_first_name;
```

### Step 4.3 – Update ORM models

```python
# Remove first_name from User model
class User(Base):
    __tablename__ = "users"
    id         = Column(Integer, primary_key=True)
    given_name = Column(Text)          # was: first_name
    email      = Column(String(255))
```

### Step 4.4 – Post-CONTRACT verification

```sql
SELECT column_name FROM information_schema.columns
 WHERE table_name='users';
-- Confirm first_name is absent
```

---

## 5. Rollback Procedures

### Rollback from EXPAND (before any backfill)

```sql
ALTER TABLE users DROP COLUMN given_name;
DROP INDEX IF EXISTS idx_users_given_name;
```

Redeploy previous application version.

### Rollback during BACKFILL

1. Stop the backfill job.
2. Drop the new column (data already in old column).
3. Redeploy previous application version.

```sql
ALTER TABLE users DROP COLUMN given_name;
```

### Rollback after CONTRACT (emergency only)

> ⚠️ This is high-risk and should be avoided by proper pre-contract validation.

1. Restore from point-in-time backup or add the column back with nulls.
2. Re-run backfill in reverse.

```sql
-- Emergency: re-add dropped column
ALTER TABLE users ADD COLUMN first_name TEXT;
UPDATE users SET first_name = given_name WHERE first_name IS NULL;
```

---

## 6. Feature Flag Management

Feature flags decouple deployment from feature activation.

### Flag Definition

```yaml
# config/feature_flags.yaml
flags:
  use_given_name_column:
    description: "Read/write given_name instead of first_name"
    default: false
    rollout_pct: 0
    owner: platform-team
```

### Gradual Rollout Sequence

```
1. Deploy code with flag OFF → verify no impact
2. Enable for 5% of traffic → monitor 10 min
3. Enable for 25% → monitor 15 min
4. Enable for 100% → monitor 30 min
5. Remove flag from code in next release
```

### Emergency Kill Switch

```bash
# Instantly disable feature for all users
feature_flags set use_given_name_column false

# Or via environment variable (requires pod restart)
kubectl set env deployment/users-api USE_GIVEN_NAME=false
```

---

## 7. Decision Tree: Which Pattern to Use

```
Is this a column rename?
├── YES → Expand/Contract with dual-write (Scenario 1)
└── NO

Is this a column split?
├── YES → Expand/Contract with transform backfill (Scenario 2)
└── NO

Is this a type change?
├── YES, lossless (e.g. int→numeric) → Shadow column + conversion backfill (Scenario 3)
├── YES, lossy (e.g. text→int)       → Shadow column + validation required
└── NO

Is this adding a NOT NULL constraint?
├── YES, PG11+, constant default → Single ALTER TABLE (safe)
├── YES, otherwise               → Multi-step: add nullable → backfill → add constraint (Scenario 4)
└── NO

Is this removing a column?
└── YES → Deprecate → stop writing → stop reading → drop (Scenario 5)

Is this an event schema change?
├── Adding optional field → Tolerant reader first, then producer (Scenario 6)
├── Adding required field → UNSAFE – make it optional with default
└── Removing field        → Deprecate in schema, consumers ignore, then remove

Is this a table restructure (normalization/denormalization)?
└── YES → Dual-write to both structures (Scenario 8)

Multiple consumers at different versions?
└── YES → API versioning + content negotiation + feature flags (Scenario 7)
```

---

## 8. Communication Plan

### Deprecation Notice (8+ weeks before removal)

Send to: internal mailing list, Slack #platform-changes, API consumers.

```
Subject: [DEPRECATION] users.first_name → users.given_name (removal: 2024-03-01)

We are migrating the users.first_name column to users.given_name.

Timeline:
  2024-01-08 – New column available; dual-write begins
  2024-01-22 – Backfill complete; both columns identical
  2024-03-01 – first_name column removed

Action required:
  Update any queries or API calls using first_name to use given_name.
  Both fields will be returned in API responses until 2024-03-01.

Questions: #platform-schema-migration
```

### Migration Day Runbook Distribution

Share this document with:
- [ ] On-call engineer
- [ ] DBA / database reliability engineer
- [ ] Service team leads

### Post-Migration Report

After CONTRACT completes, publish metrics:

- Zero-error window achieved: Y/N
- Backfill duration: ___ minutes
- Total schema migration duration: ___ hours
- Any incidents: ___ (link to post-mortems)
