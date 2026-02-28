#!/usr/bin/env python3
"""
measure_migration_time.py

Connects to PostgreSQL, executes a migration SQL statement, measures wall-clock
time, and records the result as JSON.

For backfill jobs it also measures time-per-1000-rows.

Usage:
    python measure_migration_time.py \
        --scenario 01_rename_field \
        --sql "UPDATE users SET given_name=first_name WHERE given_name IS NULL" \
        [--batch-size 1000] \
        [--dsn "postgresql://user:pass@localhost:5432/appdb"]
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras

DEFAULT_DSN = os.environ.get(
    "DATABASE_URL", "postgresql://app:app@localhost:5432/appdb"
)


def get_row_count(conn, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
        return cur.fetchone()[0]


def run_migration(conn, sql: str, batch_size: int) -> dict:
    """Execute *sql* and return timing metrics."""
    is_backfill = "WHERE" in sql.upper() and batch_size > 0
    metrics = {
        "sql": sql,
        "batch_size": batch_size if is_backfill else None,
        "is_backfill": is_backfill,
        "phases": [],
    }

    total_rows_affected = 0
    wall_start = time.perf_counter()

    if is_backfill:
        # Chunked execution: re-run until no rows remain
        iteration = 0
        while True:
            chunk_sql = f"{sql} LIMIT {batch_size}"
            iter_start = time.perf_counter()
            with conn.cursor() as cur:
                cur.execute(chunk_sql)
                rows = cur.rowcount
            conn.commit()
            iter_elapsed = time.perf_counter() - iter_start

            metrics["phases"].append(
                {
                    "iteration": iteration,
                    "rows_affected": rows,
                    "elapsed_s": round(iter_elapsed, 4),
                    "rows_per_second": round(rows / iter_elapsed, 1) if iter_elapsed > 0 else 0,
                }
            )
            total_rows_affected += rows
            iteration += 1

            if rows == 0:
                break
    else:
        with conn.cursor() as cur:
            cur.execute(sql)
            total_rows_affected = cur.rowcount
        conn.commit()

    wall_elapsed = time.perf_counter() - wall_start

    time_per_1k = None
    if total_rows_affected > 0:
        time_per_1k = round(wall_elapsed / total_rows_affected * 1000, 4)

    metrics.update(
        {
            "total_rows_affected": total_rows_affected,
            "wall_clock_s": round(wall_elapsed, 4),
            "time_per_1k_rows_s": time_per_1k,
        }
    )
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure PostgreSQL migration time")
    parser.add_argument("--scenario", required=True, help="Scenario directory name (e.g. 01_rename_field)")
    parser.add_argument("--sql", required=True, help="Migration SQL to execute")
    parser.add_argument("--batch-size", type=int, default=1000, help="Batch size for backfill iterations (default: 1000)")
    parser.add_argument("--dsn", default=DEFAULT_DSN, help="PostgreSQL DSN")
    parser.add_argument("--results-dir", default="results", help="Root results directory")
    args = parser.parse_args()

    try:
        conn = psycopg2.connect(args.dsn)
        conn.autocommit = False
    except psycopg2.OperationalError as exc:
        print(json.dumps({"error": str(exc), "status": "connection_failed"}), file=sys.stderr)
        sys.exit(1)

    try:
        metrics = run_migration(conn, args.sql, args.batch_size)
    finally:
        conn.close()

    result = {
        "scenario": args.scenario,
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "migration": metrics,
        "status": "success",
    }

    # Print to stdout
    print(json.dumps(result, indent=2))

    # Persist to results/<scenario>/migration_time.json
    out_dir = Path(args.results_dir) / args.scenario
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "migration_time.json"
    with open(out_path, "w") as fh:
        json.dump(result, fh, indent=2)
    print(f"\nSaved to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
