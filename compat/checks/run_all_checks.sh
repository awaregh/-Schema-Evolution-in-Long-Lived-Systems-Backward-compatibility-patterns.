#!/usr/bin/env bash
# =============================================================================
# compat/checks/run_all_checks.sh
# =============================================================================
# Run all backward-compatibility checks for the Schema Evolution research system.
#
# Checks performed:
#   1. SQL migration files in db/migrations/
#   2. API spec compatibility:  users_v1.yaml → users_v2.yaml
#   3. Event schema compatibility:
#      • user.registered v1 → v2
#      • subscription.created v1 → v2
#
# Exit codes:
#   0  – all checks passed (warnings do not cause failure)
#   1  – one or more checks failed
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Paths (relative to repository root)
# ---------------------------------------------------------------------------

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPAT_DIR="${REPO_ROOT}/compat/checks"
MIGRATIONS_DIR="${REPO_ROOT}/db/migrations"
CONTRACTS_API="${REPO_ROOT}/contracts/api"
CONTRACTS_EVENTS="${REPO_ROOT}/contracts/events"

DB_CHECK="${COMPAT_DIR}/check_db_migration.py"
API_CHECK="${COMPAT_DIR}/check_api_compat.py"
EVENT_CHECK="${COMPAT_DIR}/check_event_compat.py"

# ---------------------------------------------------------------------------
# Colour helpers (degrade gracefully when not in a TTY)
# ---------------------------------------------------------------------------

if [ -t 1 ]; then
  RED='\033[31m'; YELLOW='\033[33m'; GREEN='\033[32m'; BOLD='\033[1m'; RESET='\033[0m'
else
  RED=''; YELLOW=''; GREEN=''; BOLD=''; RESET=''
fi

pass() { echo -e "${GREEN}[PASS]${RESET} $*"; }
warn() { echo -e "${YELLOW}[WARN]${RESET} $*"; }
fail() { echo -e "${RED}[FAIL]${RESET} $*"; }
header() { echo -e "\n${BOLD}==> $*${RESET}"; }

# ---------------------------------------------------------------------------
# Track overall result
# ---------------------------------------------------------------------------

OVERALL_FAILED=0

run_python() {
    # Run a python check script and propagate non-zero exit as a failure flag.
    if python3 "$@"; then
        return 0
    else
        OVERALL_FAILED=1
        return 0  # continue script despite failure
    fi
}

# ---------------------------------------------------------------------------
# 1. SQL migration files
# ---------------------------------------------------------------------------

header "SQL Migration Safety Checks"

if [ ! -d "${MIGRATIONS_DIR}" ]; then
    warn "Migrations directory not found: ${MIGRATIONS_DIR} – skipping."
else
    shopt -s nullglob
    SQL_FILES=("${MIGRATIONS_DIR}"/*.sql)
    shopt -u nullglob

    if [ ${#SQL_FILES[@]} -eq 0 ]; then
        warn "No SQL migration files found in ${MIGRATIONS_DIR}"
    else
        for sql_file in "${SQL_FILES[@]}"; do
            echo "  Checking: $(basename "${sql_file}")"
            run_python "${DB_CHECK}" "${sql_file}"
        done
    fi
fi

# ---------------------------------------------------------------------------
# 2. API spec compatibility
# ---------------------------------------------------------------------------

header "API Compatibility Checks"

OLD_API="${CONTRACTS_API}/users_v1.yaml"
NEW_API="${CONTRACTS_API}/users_v2.yaml"

if [ ! -f "${OLD_API}" ] || [ ! -f "${NEW_API}" ]; then
    warn "API spec file(s) not found – skipping API compat check."
    warn "  Expected: ${OLD_API}"
    warn "  Expected: ${NEW_API}"
else
    run_python "${API_CHECK}" "${OLD_API}" "${NEW_API}"
fi

# ---------------------------------------------------------------------------
# 3. Event schema compatibility
# ---------------------------------------------------------------------------

header "Event Schema Compatibility Checks"

check_event_pair() {
    local old_schema="$1"
    local new_schema="$2"
    local label="$3"

    if [ ! -f "${old_schema}" ] || [ ! -f "${new_schema}" ]; then
        warn "${label}: schema file(s) not found – skipping."
        warn "  Expected: ${old_schema}"
        warn "  Expected: ${new_schema}"
        return
    fi

    echo "  Checking: ${label}"
    run_python "${EVENT_CHECK}" "${old_schema}" "${new_schema}"
}

check_event_pair \
    "${CONTRACTS_EVENTS}/user_registered_v1.json" \
    "${CONTRACTS_EVENTS}/user_registered_v2.json" \
    "user.registered v1 → v2"

check_event_pair \
    "${CONTRACTS_EVENTS}/subscription_created_v1.json" \
    "${CONTRACTS_EVENTS}/subscription_created_v2.json" \
    "subscription.created v1 → v2"

# ---------------------------------------------------------------------------
# Final result
# ---------------------------------------------------------------------------

echo ""
echo "============================================================"
if [ "${OVERALL_FAILED}" -ne 0 ]; then
    fail "One or more compatibility checks FAILED."
    echo ""
    exit 1
else
    pass "All compatibility checks PASSED."
    echo ""
    exit 0
fi
