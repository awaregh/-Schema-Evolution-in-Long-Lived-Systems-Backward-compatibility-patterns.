#!/usr/bin/env bash
# run_load_tests.sh
#
# Runs Locust for each schema-evolution scenario and saves CSV results.
# Requires: locust (pip install locust==2.17.0)
#
# Usage:
#   ./load_tests/run_load_tests.sh [--users 100] [--spawn-rate 10] [--run-time 60s]
#
# Output:
#   results/<scenario>/locust_stats.csv
#   results/<scenario>/locust_stats_history.csv
#   results/<scenario>/locust_failures.csv

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RESULTS_DIR="${REPO_ROOT}/results"

USERS="${USERS:-100}"
SPAWN_RATE="${SPAWN_RATE:-10}"
RUN_TIME="${RUN_TIME:-60s}"
V1_HOST="${V1_HOST:-http://localhost:8001}"
V2_HOST="${V2_HOST:-http://localhost:8002}"

SCENARIOS=(
  "01_rename_field"
  "02_split_column"
  "03_type_change"
  "04_add_not_null"
  "05_remove_field"
  "06_new_event_field"
  "07_dual_consumer"
  "08_denormalization"
)

check_service() {
  local url="$1"
  if curl --silent --fail --max-time 3 "${url}/health" > /dev/null 2>&1; then
    return 0
  fi
  echo "WARNING: ${url}/health not reachable – skipping Locust run" >&2
  return 1
}

run_locust() {
  local scenario="$1"
  local out_dir="${RESULTS_DIR}/${scenario}"
  mkdir -p "${out_dir}"

  echo "============================================"
  echo "Scenario: ${scenario}"
  echo "Users: ${USERS}, Spawn rate: ${SPAWN_RATE}, Duration: ${RUN_TIME}"
  echo "============================================"

  locust \
    -f "${SCRIPT_DIR}/locustfile.py" \
    --headless \
    --users "${USERS}" \
    --spawn-rate "${SPAWN_RATE}" \
    --run-time "${RUN_TIME}" \
    --host "${V1_HOST}" \
    --csv "${out_dir}/locust_stats" \
    --html "${out_dir}/locust_report.html" \
    --exit-code-on-error 0 \
    2>&1 | tee "${out_dir}/locust_run.log"

  echo "Results saved to ${out_dir}"
}

run_mixed_version() {
  local scenario="07_dual_consumer"
  local out_dir="${RESULTS_DIR}/${scenario}"
  mkdir -p "${out_dir}"

  echo "============================================"
  echo "Scenario: ${scenario} (mixed-version)"
  echo "============================================"

  V1_BASE_URL="${V1_HOST}" V2_BASE_URL="${V2_HOST}" \
  locust \
    -f "${SCRIPT_DIR}/scenarios/mixed_version_test.py" \
    --headless \
    --users "${USERS}" \
    --spawn-rate "${SPAWN_RATE}" \
    --run-time "${RUN_TIME}" \
    --host "${V1_HOST}" \
    --csv "${out_dir}/locust_mixed_stats" \
    --html "${out_dir}/locust_mixed_report.html" \
    --exit-code-on-error 0 \
    2>&1 | tee "${out_dir}/locust_mixed_run.log"
}

main() {
  echo "Checking services..."
  V1_UP=true
  V2_UP=true
  check_service "${V1_HOST}" || V1_UP=false
  check_service "${V2_HOST}" || V2_UP=false

  if [ "${V1_UP}" = "false" ] && [ "${V2_UP}" = "false" ]; then
    echo "ERROR: Neither v1 nor v2 service is reachable. Start services first." >&2
    exit 1
  fi

  for scenario in "${SCENARIOS[@]}"; do
    if [ "${scenario}" = "07_dual_consumer" ]; then
      run_mixed_version
    else
      run_locust "${scenario}"
    fi
    echo ""
  done

  echo "All load tests complete."
  echo "Generate summary report with:"
  echo "  python analysis/generate_report.py --results-dir results"
}

main "$@"
