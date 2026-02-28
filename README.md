# Schema Evolution in Long-Lived Systems

> **Backward Compatibility Patterns for APIs, Events, and Databases**

A research implementation and empirical study of eight real-world schema
evolution scenarios across a three-service microservices architecture, covering
PostgreSQL database migrations, REST API versioning, and event schema evolution.
Every scenario is implemented with both the **unsafe direct approach** (baseline)
and one or more **safe backward-compatible patterns**, with measured outcomes
for error rate, migration time, rollback complexity, and latency overhead.

📄 **Full research paper:** [`paper/paper.md`](paper/paper.md)

---

## Overview

Schema evolution — changing the structure of data in a live system — is one
of the most operationally hazardous activities in software engineering.  In
distributed systems with rolling deployments, an unsafe schema change instantly
produces errors at 100% rate while old pods are still running.

This repository demonstrates that zero-downtime schema evolution is achievable
at low operational cost when structured patterns are applied:

- **0% error rate** across all 8 scenarios using safe patterns (vs. 100% for
  unsafe approaches)
- **2.8–5.8% write latency overhead** for dual-write (negligible vs. incident cost)
- **≈12 300 rows/s** backfill throughput at optimal batch size
- **1.8 s rollback time** with feature flags (vs. 8.4 min with pod restarts)

---

## Architecture

```
  ┌─────────────────────────────────────────────────────────────┐
  │                     CLIENT REQUESTS                          │
  └────────┬──────────────────────┬───────────────────────────┘
           │                      │
           ▼                      ▼
  ┌────────────────┐    ┌─────────────────┐
  │  users-v1:8001 │    │  users-v2:8002  │
  │  (first_name)  │    │  (given_name)   │
  └───────┬────────┘    └────────┬────────┘
          │     dual-write        │
          └──────────┬────────────┘
                     │
                     ▼
          ┌──────────────────────┐
          │   PostgreSQL 15.2    │◄──── backfill worker
          │  schema_evolution DB │
          │                      │
          │  ┌─────────────────┐ │
          │  │     users       │ │  ← both first_name + given_name during migration
          │  ├─────────────────┤ │
          │  │  subscriptions  │ │
          │  ├─────────────────┤ │
          │  │     events      │ │
          │  └─────────────────┘ │
          └────────┬─────────────┘
                   │
       ┌───────────┼───────────┐
       │           │           │
       ▼           ▼           ▼
  ┌─────────┐ ┌─────────┐ ┌──────────┐
  │billing  │ │analytics│ │ Redis 7  │
  │ :8003   │ │  :8004  │ │ (flags)  │
  └─────────┘ └─────────┘ └──────────┘
```

The `users-v1` and `users-v2` containers run the **same codebase**, differentiated
by the `FEATURE_FLAG_GIVEN_NAME` environment variable — modelling a rolling
deployment where old and new pods coexist.

---

## Quick Start

**Prerequisites:** Docker and Docker Compose.

```bash
# 1. Clone the repository
git clone <repo-url>
cd schema-evolution-research

# 2. Start all services
docker-compose -f infra/docker-compose.yml up -d

# 3. Verify services are healthy
docker-compose -f infra/docker-compose.yml ps

# 4. Check users-v1 is running the legacy schema
curl http://localhost:8001/v1/users/1

# 5. Check users-v2 is running the new schema
curl http://localhost:8002/v2/users/1

# 6. Run all compatibility checks
bash compat/checks/run_all_checks.sh
```

---

## Services

| Service | Port | Version | Description |
|---------|:----:|:-------:|-------------|
| `users-v1` | 8001 | v1 | Users API — legacy `first_name` schema |
| `users-v2` | 8002 | v2 | Users API — new `given_name` schema |
| `billing` | 8003 | v1 | Subscriptions and payments |
| `analytics` | 8004 | v1 | Event aggregation and reporting |
| `postgres` | 5432 | 15 | Shared PostgreSQL database |
| `redis` | 6379 | 7 | Feature flag state and caching |
| `backfill` | — | — | Background data migration worker |

API documentation (Swagger UI) is available at:
- `http://localhost:8001/docs` — Users v1
- `http://localhost:8002/docs` — Users v2
- `http://localhost:8003/docs` — Billing
- `http://localhost:8004/docs` — Analytics

---

## Evolution Scenarios

Eight scenarios covering the full taxonomy of schema evolution types:

| # | Scenario | Pattern | Risk | Results |
|---|----------|---------|:----:|---------|
| 1 | Rename field: `first_name` → `given_name` | Expand/Contract + Dual-Write | 🟢 Low | [results/01_rename_field/](results/01_rename_field/README.md) |
| 2 | Split column: `name` → `first_name` + `last_name` | Expand/Contract + Transform | 🟡 Medium | [results/02_split_column/](results/02_split_column/README.md) |
| 3 | Type change: `amount_cents` (int) → `amount` (decimal) | Shadow Column + Conversion | 🟡 Medium | [results/03_type_change/](results/03_type_change/README.md) |
| 4 | Add NOT NULL column with default (`locale`) | Multi-Step Constraint | 🟢 Low | [results/04_add_not_null/](results/04_add_not_null/README.md) |
| 5 | Remove deprecated field (`legacy_notes`) | Deprecate → Ignore → Remove | 🟢 Low | [results/05_remove_field/](results/05_remove_field/README.md) |
| 6 | New event field with old consumer | Tolerant Reader + Additive | 🟢 Low | [results/06_new_event_field/](results/06_new_event_field/README.md) |
| 7 | Dual consumer versions (v1 + v2 simultaneously) | API Versioning + Feature Flags | 🟢 Low | [results/07_dual_consumer/](results/07_dual_consumer/README.md) |
| 8 | Denormalization: embed → separate table | Dual-Write Both Schemas | 🔴 High | [results/08_denormalization/](results/08_denormalization/README.md) |

**Summary results:**

| Pattern | Error Rate (safe) | Error Rate (unsafe) | Latency Overhead |
|---------|:-----------------:|:-------------------:|:----------------:|
| Expand/Contract + Dual-Write | **0%** | 100% | +2.8–5.8% |
| Shadow Column | **0%** | 100% | +2.6% |
| Multi-Step Constraint | **0%** | 100% (pre-PG11) | None |
| Tolerant Reader | **0%** | 37/1000 events | None |
| Feature Flag Cutover | **0%** | 0.3% | None |

---

## Running Compatibility Checks

A single shell script runs all three compatibility checkers (SQL, API, Event):

```bash
bash compat/checks/run_all_checks.sh
```

Expected output:

```
==> SQL Migration Safety Checks
  Checking: 001_users_baseline.sql
  Checking: 002_expand_given_name.sql
  ...

==> API Compatibility Checks
  [PASS] users_v1.yaml → users_v2.yaml: 0 breaking changes

==> Event Schema Compatibility Checks
  [PASS] user.registered v1 → v2: 0 breaking changes
  [PASS] subscription.created v1 → v2: 0 breaking changes

============================================================
[PASS] All compatibility checks PASSED.
```

The script exits with code `1` if any breaking change is detected, making it
suitable as a CI merge gate.

### Individual Checkers

```bash
# Check a single SQL migration file
python3 compat/checks/check_db_migration.py db/migrations/002_expand_given_name.sql

# Check API spec compatibility between two OpenAPI files
python3 compat/checks/check_api_compat.py \
    contracts/api/users_v1.yaml \
    contracts/api/users_v2.yaml

# Check event schema compatibility
python3 compat/checks/check_event_compat.py \
    contracts/events/user_registered_v1.json \
    contracts/events/user_registered_v2.json
```

---

## Running Tests

```bash
# Install test dependencies
cd tests && pip install -r requirements.txt

# Run all tests
pytest

# Run specific test suites
pytest tests/migrations/        # migration safety tests
pytest tests/contract/          # API and event contract tests
pytest tests/rollback/          # rollback scenario tests

# Run with verbose output
pytest -v

# Run with coverage report
pytest --cov=compat --cov-report=term-missing
```

Test categories:

| Suite | What it tests |
|-------|--------------|
| `tests/migrations/` | SQL migration safety rules (unsafe pattern detection) |
| `tests/contract/` | API spec compatibility (OpenAPI diff) and event schema compat |
| `tests/rollback/` | Rollback procedure correctness for each scenario |

---

## Running Load Tests

Load tests use [Locust](https://locust.io/) with 100 virtual users at 10 req/s.

```bash
# Install locust
cd load_tests && pip install -r requirements.txt

# Run headless (CI mode) — 60 seconds, 100 users
bash load_tests/run_load_tests.sh

# Run with web UI (interactive mode)
locust -f load_tests/locustfile.py \
    --host http://localhost:8001 \
    --web-port 8089
# Then open http://localhost:8089

# Run the mixed-version scenario (v1 + v2 simultaneously)
locust -f load_tests/scenarios/mixed_version_test.py \
    --host http://localhost:8001 \
    --headless \
    --users 100 \
    --spawn-rate 10 \
    --run-time 60s
```

Load test scenarios:
- **`locustfile.py`**: Standard read/write traffic on the users API
- **`scenarios/mixed_version_test.py`**: Mixed v1/v2 traffic for Scenario 7
  (dual consumer versions)

---

## Running Analysis Scripts

The `analysis/` directory contains scripts for measuring migration metrics:

```bash
# Measure migration time for a scenario
python analysis/measure_migration_time.py \
    --scenario 01_rename_field \
    --sql "UPDATE users SET given_name=first_name WHERE given_name IS NULL" \
    --batch-size 1000

# Measure error rate during migration window
python analysis/measure_error_rate.py \
    --scenario 01_rename_field \
    --duration 60 \
    --rps 10

# Monitor column population progress during backfill
python analysis/measure_column_reads.py \
    --scenario 01_rename_field \
    --table users \
    --old-column first_name \
    --new-column given_name \
    --interval 30 \
    --duration 600

# Generate full results report
python analysis/generate_report.py --output results/report.json
```

---

## Paper

The full research paper is available at **[`paper/paper.md`](paper/paper.md)**.

**Abstract:** An empirical study of eight schema evolution scenarios across a
three-service distributed system.  Key findings: Expand/Contract achieves 0%
error rate (vs. 100% for unsafe direct changes); dual-write adds only 2.8–5.8%
latency overhead; feature flag cutovers reduce rollback time from 8.4 min to
1.8 s; automated CI checks block 100% of unsafe patterns.

**Sections:**
1. Introduction — Why schema evolution breaks systems
2. Background — CAP theorem, event sourcing, API versioning, Alembic
3. System Architecture — Three-service reference implementation
4. Evolution Scenarios and Methodology — All 8 scenarios with safety analysis
5. Backward Compatibility Patterns — DB, API, and Event patterns in detail
6. Automated Compatibility Checks — CI-integrated checker implementation
7. Results — Tables of measured outcomes, backfill performance, latency overhead
8. Discussion — Tradeoffs, operational risk matrix, cost of backward compat
9. Recommendations — Decision tree and playbook
10. Threats to Validity
11. Conclusion and Future Work
12. References (20 citations)

---

## Directory Structure

```
.
├── analysis/                   # Measurement and reporting scripts
│   ├── generate_report.py      # Generate consolidated results report
│   ├── measure_column_reads.py # Monitor backfill column population progress
│   ├── measure_error_rate.py   # Measure HTTP error rates during migrations
│   └── measure_migration_time.py # Time backfill jobs at various batch sizes
│
├── compat/                     # Automated compatibility checkers
│   ├── checks/
│   │   ├── check_api_compat.py    # OpenAPI spec diff — detect breaking changes
│   │   ├── check_db_migration.py  # SQL migration safety rules
│   │   ├── check_event_compat.py  # JSON Schema event compatibility
│   │   └── run_all_checks.sh      # Orchestrate all checks (CI entrypoint)
│   └── rules/
│       ├── api_compat_rules.py    # API breaking-change rule definitions
│       ├── db_migration_rules.py  # SQL anti-pattern rule definitions
│       └── event_compat_rules.py  # Event schema compatibility rule definitions
│
├── contracts/                  # Versioned schema contracts
│   ├── api/
│   │   ├── users_v1.yaml       # OpenAPI spec for Users API v1
│   │   └── users_v2.yaml       # OpenAPI spec for Users API v2
│   ├── db/
│   │   ├── users_schema_v1.sql # Baseline users table DDL
│   │   └── users_schema_v2.sql # Post-migration users table DDL
│   └── events/
│       ├── subscription_created_v1.json  # Event schema (JSON Schema)
│       ├── subscription_created_v2.json
│       ├── user_registered_v1.json
│       └── user_registered_v2.json
│
├── db/                         # Database migrations and seed data
│   ├── migrations/
│   │   ├── 001_users_baseline.sql           # Initial schema
│   │   ├── 002_expand_given_name.sql        # Scenario 1: Expand phase
│   │   ├── 003_backfill_given_name.sql      # Scenario 1: Backfill
│   │   ├── 004_contract_drop_first_name.sql # Scenario 1: Contract phase
│   │   ├── 005_subscriptions_baseline.sql   # Billing schema baseline
│   │   ├── 006_expand_amount_decimal.sql    # Scenario 3: Type change expand
│   │   ├── 007_add_not_null_with_default.sql # Scenario 4: NOT NULL add
│   │   └── 008_event_schema_v2.sql          # Scenario 6: Event table update
│   └── seeds/
│       ├── 01_users.sql        # Test user data (1M rows)
│       ├── 02_subscriptions.sql # Test subscription data
│       └── 03_events.sql       # Test event data
│
├── docs/                       # Operational documentation
│   ├── anti_patterns.md        # 10 dangerous migration anti-patterns to avoid
│   ├── evolution_playbook.md   # Step-by-step migration runbook
│   └── findings.md             # Empirical research findings summary
│
├── infra/                      # Infrastructure configuration
│   ├── docker-compose.yml      # All services: postgres, redis, 4 app services
│   └── postgres-init.sql       # Database initialisation (databases, roles)
│
├── load_tests/                 # Locust load test definitions
│   ├── locustfile.py           # Standard read/write load test
│   ├── requirements.txt        # locust + dependencies
│   ├── run_load_tests.sh       # Headless CI load test runner
│   └── scenarios/
│       └── mixed_version_test.py # Scenario 7: mixed v1/v2 traffic
│
├── paper/
│   └── paper.md                # Full research paper (4000+ words)
│
├── results/                    # Per-scenario results and documentation
│   ├── 01_rename_field/README.md     # Expand/Contract walkthrough
│   ├── 02_split_column/README.md     # Column split walkthrough
│   ├── 03_type_change/README.md      # Type change walkthrough
│   ├── 04_add_not_null/README.md     # NOT NULL addition walkthrough
│   ├── 05_remove_field/README.md     # Deprecation walkthrough
│   ├── 06_new_event_field/README.md  # Event schema evolution walkthrough
│   ├── 07_dual_consumer/README.md    # Dual API version walkthrough
│   └── 08_denormalization/README.md  # Denormalization walkthrough
│
├── services/                   # Microservice implementations
│   ├── analytics/              # Analytics service (FastAPI)
│   │   ├── app/                # Application code (models, schemas, API routes)
│   │   ├── migrations/         # Alembic migrations
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   ├── backfill/               # Background backfill worker
│   │   ├── worker.py           # Batched update loop
│   │   ├── models.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   ├── billing/                # Billing service (FastAPI)
│   │   ├── app/
│   │   ├── migrations/
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   └── users/                  # Users service (FastAPI) — v1 and v2
│       ├── app/
│       │   ├── api/
│       │   │   ├── v1/users.py  # V1 API (first_name)
│       │   │   └── v2/users.py  # V2 API (given_name)
│       │   ├── models/
│       │   └── schemas/
│       ├── migrations/
│       ├── Dockerfile
│       └── requirements.txt
│
└── tests/                      # Test suites
    ├── conftest.py             # Shared fixtures and database setup
    ├── requirements.txt        # pytest + dependencies
    ├── contract/
    │   ├── test_api_compat.py  # API contract tests
    │   └── test_event_compat.py # Event schema contract tests
    ├── migrations/
    │   └── test_migration_safety.py # SQL safety rule tests
    └── rollback/
        └── test_rollback_scenarios.py # Rollback procedure tests
```

---

## Contributing

### Adding a New Scenario

1. **Create the results directory:**

   ```bash
   mkdir -p results/09_your_scenario
   ```

2. **Write the scenario README** in `results/09_your_scenario/README.md`
   following the structure of existing scenario READMEs:
   - What the change is
   - Why it's dangerous without proper patterns
   - Phase 1: EXPAND (SQL + application code)
   - Phase 2: BACKFILL (batched migration)
   - Phase 3: CONTRACT (cleanup)
   - Safe vs. Unsafe comparison
   - Rollback procedures
   - Expected results table

3. **Add migration files** in `db/migrations/` with sequential numbering:

   ```bash
   touch db/migrations/009_expand_your_scenario.sql
   touch db/migrations/010_contract_your_scenario.sql
   ```

4. **Add contract files** if introducing new API or event schemas:

   ```bash
   touch contracts/api/your_resource_v1.yaml
   touch contracts/events/your_event_v1.json
   ```

5. **Add tests** in the appropriate test directory:

   ```bash
   touch tests/migrations/test_your_scenario_migration.py
   touch tests/contract/test_your_scenario_compat.py
   ```

6. **Update the compatibility check** if your scenario introduces a new
   anti-pattern to detect, in `compat/rules/db_migration_rules.py`.

7. **Run the full test suite** to verify nothing is broken:

   ```bash
   cd tests && pytest -v
   bash compat/checks/run_all_checks.sh
   ```

### Code Standards

- All migration SQL files must pass `compat/checks/check_db_migration.py`
  with zero errors (warnings allowed for documented exceptions).
- All API spec changes must pass `compat/checks/check_api_compat.py`.
- All event schema changes must pass `compat/checks/check_event_compat.py`.
- New service code must follow the existing FastAPI + SQLAlchemy + Alembic
  pattern in `services/users/`.
- Backfill jobs must use batched updates (default: 1 000 rows) with inter-batch
  pauses (default: 50 ms).

---

## Key Documentation

| Document | Description |
|----------|-------------|
| [`paper/paper.md`](paper/paper.md) | Full research paper with methodology, results, and references |
| [`docs/findings.md`](docs/findings.md) | Empirical findings summary (F1–F5 + metrics table) |
| [`docs/evolution_playbook.md`](docs/evolution_playbook.md) | Step-by-step operations runbook for zero-downtime migrations |
| [`docs/anti_patterns.md`](docs/anti_patterns.md) | 10 dangerous anti-patterns with real-world incident examples |

---

## License

This project is released for research and educational purposes.
