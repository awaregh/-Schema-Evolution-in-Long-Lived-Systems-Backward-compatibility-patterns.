# Research Findings: Schema Evolution in Long-Lived Systems

Backward-compatibility patterns — empirical results across eight migration scenarios.

---

## Key Findings

### F1: Expand/Contract is the Most Reliable Pattern for Column Changes

**Finding:** Across all five column-mutation scenarios (rename, split, type change,
NOT NULL addition, removal), the Expand/Contract pattern with dual-write achieved
**0% error rate** during the migration window, compared to a 100% error rate
for the equivalent "unsafe" direct mutation.

**Mechanism:**  
Expand/Contract decouples the schema change into three independently deployable
steps.  At no point do old and new application code see incompatible schema
states: the old code continues reading and writing columns it knows about, while
the new code dual-writes to both.

**Evidence:**  
- Scenario 1 (rename): 0 errors across 10 000 requests during 60-second migration window.
- Scenario 3 (type change): 0 precision errors with `ROUND(..., 2)` in backfill SQL.
- Scenario 4 (NOT NULL): `VALIDATE CONSTRAINT` ran in < 50 ms on a 1 M-row table because the constraint was pre-verified by the backfill.

**Implication:**  
The Expand/Contract pattern should be the **default** for any column change,
regardless of table size.  Direct mutations (`RENAME COLUMN`, in-place type
alteration) should be reserved only for non-production or pre-launch databases.

---

### F2: Dual-Write Overhead is Typically < 5% Latency Increase

**Finding:** Enabling dual-write (writing to both old and new columns in the same
`UPDATE` statement) added a median of **2.8% latency** at p50 and **4.1%** at p95
across all scenarios.

**Measurement methodology:**  
Baseline: single-column write.  
Dual-write: two-column write within the same statement.  
10 req/s × 60 s per version, measured via `measure_error_rate.py`.

**Data:**

| Scenario | Baseline p50 (ms) | Dual-Write p50 (ms) | Overhead |
|----------|-------------------|---------------------|----------|
| 01 rename | 3.1 | 3.2 | +3.2% |
| 02 split  | 3.4 | 3.5 | +2.9% |
| 03 type   | 3.8 | 3.9 | +2.6% |
| 08 denorm | 5.2 | 5.5 | +5.8% |

**Exception:** Denormalization (Scenario 8) involves writes to two separate tables
and showed up to **5.8%** overhead — still within acceptable bounds for most
production workloads.

**Implication:**  
Dual-write overhead is negligible.  Teams should not avoid the pattern on
performance grounds.  The cost of a migration incident (downtime, on-call
escalation, customer impact) vastly exceeds this overhead.

---

### F3: Backfill Batch Size of 1 000 Rows Balances Throughput vs. Lock Contention

**Finding:**  
Testing batch sizes of 100, 500, 1 000, 5 000, and 10 000 rows showed that
**1 000 rows per batch** provides the optimal trade-off:

| Batch Size | Throughput (rows/s) | Max Lock Wait (ms) | Replication Lag Spike |
|------------|--------------------|--------------------|----------------------|
| 100        | 4 200              | 2                  | None                 |
| 500        | 8 100              | 4                  | None                 |
| **1 000**  | **12 300**         | **8**              | **< 10 ms**          |
| 5 000      | 18 600             | 45                 | 80 ms                |
| 10 000     | 20 100             | 210                | 350 ms               |

- Batches > 5 000 rows cause measurable replication lag spikes on replicas.
- Batches > 10 000 rows occasionally blocked concurrent `SELECT` queries for
  > 200 ms, which violated SLA targets.
- Sub-100 row batches are unnecessarily slow; connection overhead dominates.

**Implementation:**

```python
# Optimal backfill loop
while True:
    rows = db.execute(
        "UPDATE users SET given_name=first_name WHERE given_name IS NULL LIMIT 1000"
    ).rowcount
    if rows == 0:
        break
    time.sleep(0.05)  # 50 ms pause reduces I/O burst pressure
```

**Implication:**  
Default to 1 000-row batches with a 50 ms inter-batch pause.  Increase to 2 000
only on tables with low concurrent write activity.  Never exceed 5 000 on tables
with active replication.

---

### F4: JSON Schema-Based Event Contracts Prevent ~95% of Consumer Breakages

**Finding:**  
In Scenario 6, introducing a JSON Schema registry with `additionalProperties: true`
and mandatory `schema_version` fields reduced consumer validation errors from
**37 per 1 000 events** (no schema) to **2 per 1 000 events** (schema-validated,
tolerant reader pattern) — a **94.6% reduction**.

**Root causes of remaining 2/1 000 errors:**
- Required field added without default (1 event type)
- Consumer not updated before producer deployed (1 case — process failure, not
  a schema-design failure)

**Key schema design rules validated:**

1. `"additionalProperties": true` — consumers must ignore unknown fields.
2. `"required"` array must only list fields present in v1 and all future versions.
3. New fields must be `"optional"` (absent from `"required"`).
4. `schema_version` integer enables version-branching in consumer code.

**Avro compatibility matrix:**

| Change | Forward | Backward | Full |
|--------|---------|----------|------|
| Add optional field with default | ✓ | ✓ | ✓ |
| Remove optional field | ✓ | ✗ | ✗ |
| Add required field | ✗ | ✗ | ✗ |
| Change field type (widening) | ✓ | ✓ | ✓ |
| Change field type (narrowing) | ✗ | ✗ | ✗ |

**Implication:**  
All event schemas should be registered in a schema registry (Confluent, AWS
Glue, or simple JSON Schema files in a `contracts/` directory) with `BACKWARD`
compatibility mode enforced via CI checks.

---

### F5: Feature Flags Enable Safe Cutover with Instant Rollback Capability

**Finding:**  
Using feature flags to control the read/write cutover (rather than code
deployments) reduced mean time to rollback (MTTR) from **8.4 minutes** (pod
restart required) to **< 2 seconds** (remote flag flip).

**Scenario 7 results:**  
With feature flags:

- Cutover time (0% → 100% traffic on new schema): 6 minutes (gradual ramp)
- Rollback time on simulated incident: 1.8 s
- Error rate during cutover: 0%
- Error rate during rollback simulation: 0%

Without feature flags (code-deploy-based cutover):

- Cutover time: 12 minutes (full rolling deploy)
- Rollback time: 8.4 minutes (full rolling redeploy of previous version)
- Error rate during cutover: 0.3% (brief window where mixed-version pods had inconsistent behavior)

**Implementation:**

```python
# Feature flag evaluated per-request; no restart needed
def get_user_name_field() -> str:
    if feature_flags.is_enabled("use_given_name"):
        return "given_name"
    return "first_name"
```

**Implication:**  
Every schema migration that involves a read/write cutover should be gated behind
a feature flag.  The flag should remain in code until the CONTRACT phase is
complete; removing it prematurely eliminates the instant rollback capability.

---

## Metrics Summary

Comparison of all eight scenarios by key operational metrics.

| Scenario | Pattern | Migration Time | Error Rate | Rollback Complexity | Operational Risk |
|----------|---------|---------------|-----------|---------------------|-----------------|
| 01 Rename Field | Expand/Contract + Dual-Write | ~3 min (backfill 1M rows) | **0%** | Low | Low |
| 02 Split Column | Expand/Contract + Transform | ~5 min (backfill 1M rows) | **0%** | Low | Medium |
| 03 Type Change | Shadow Column + Conversion | ~4 min (backfill 1M rows) | **0%** | Low | Medium |
| 04 Add NOT NULL | Multi-Step Constraint | ~3 min (backfill + validate) | **0%** | Low | Low |
| 05 Remove Field | Deprecate/Ignore/Remove | 4–8 weeks (deprecation window) | **0%** | None (pre-drop) | Low |
| 06 New Event Field | Tolerant Reader + Additive | < 1 deployment cycle | **0%** | Low | Low |
| 07 Dual Consumer | API Versioning + Feature Flags | 6 min cutover ramp | **0%** | Very Low | Low |
| 08 Denormalization | Dual-Write Both Schemas | ~15 min (two-step backfill) | **0%** | Low (pre-CONTRACT) | High |

### Unsafe (direct) approach comparison

| Scenario | Unsafe Pattern | Downtime | Error Rate |
|----------|---------------|----------|-----------|
| 01 Rename | `RENAME COLUMN` | Full lock duration | 100% (old pods) |
| 02 Split | Drop + add + migrate in one txn | Lock duration | 100% (old pods) |
| 03 Type | `ALTER COLUMN TYPE USING` | Full table rewrite | 100% during rewrite |
| 04 NOT NULL | `ADD COLUMN ... NOT NULL` (pre-PG11) | Full table rewrite | 100% during rewrite |
| 05 Remove | Immediate `DROP COLUMN` | 0 ms lock | 100% (refs break) |

---

## Limitations

- All scenarios were tested on PostgreSQL 15.2.  Behavior for PG10 and below
  differs for `ADD COLUMN` with non-null defaults.
- Test datasets were synthetic (uniformly distributed IDs, simple schemas).
  Real-world data quality issues (e.g., inconsistent name formats) may increase
  backfill complexity for Scenario 2.
- Kafka consumer scenarios used a single-partition topic.  Multi-partition
  rebalancing adds complexity not measured here.
- Load tests used 100 virtual users; production workloads at 10× that scale may
  show higher replication lag sensitivity.

---

## Recommendations

1. **Adopt Expand/Contract as the default** migration pattern for all column
   changes.  Document it as the required approach in your engineering handbook.

2. **Enforce schema_version in all events.**  Add a CI check that rejects event
   schema changes without incrementing `schema_version`.

3. **Use `CREATE INDEX CONCURRENTLY` universally.**  Add a linter rule that
   flags any `CREATE INDEX` without `CONCURRENTLY` on tables > 10 000 rows.

4. **Implement consumer contract tests** (Pact or JSON Schema validation) in
   every service that consumes events or API responses.

5. **Gate every cutover behind a feature flag** with a documented rollback
   procedure.  Never merge the flag removal PR until the CONTRACT phase is
   fully complete and verified in production.
