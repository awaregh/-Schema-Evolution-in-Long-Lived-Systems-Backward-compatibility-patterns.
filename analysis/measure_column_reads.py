#!/usr/bin/env python3
"""
measure_column_reads.py

Polls the database every 30 seconds during a backfill window and records the
percentage of rows that have been migrated from the old column to the new one.

Usage:
    python measure_column_reads.py \
        --scenario 01_rename_field \
        --table users \
        --old-column first_name \
        --new-column given_name \
        [--interval 30] \
        [--duration 600] \
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

DEFAULT_DSN = os.environ.get(
    "DATABASE_URL", "postgresql://app:app@localhost:5432/appdb"
)


def sample(conn, table: str, new_col: str) -> dict:
    """Return counts of NULL vs NOT NULL for *new_col* in *table*."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                COUNT(*) FILTER (WHERE {new_col} IS NOT NULL) AS migrated,
                COUNT(*) FILTER (WHERE {new_col} IS NULL)     AS remaining,
                COUNT(*)                                       AS total
            FROM {table}
            """,  # noqa: S608
        )
        row = cur.fetchone()
    migrated, remaining, total = row
    pct_done = round(migrated / total * 100, 2) if total else 0.0
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "migrated_rows": migrated,
        "remaining_rows": remaining,
        "total_rows": total,
        "pct_migrated": pct_done,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor column backfill progress")
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--table", default="users", help="Table to monitor")
    parser.add_argument("--old-column", default="first_name", help="Column being replaced")
    parser.add_argument("--new-column", default="given_name", help="New column being filled")
    parser.add_argument("--interval", type=int, default=30, help="Poll interval in seconds")
    parser.add_argument("--duration", type=int, default=600, help="Total monitoring window in seconds (0 = run once)")
    parser.add_argument("--dsn", default=DEFAULT_DSN)
    parser.add_argument("--results-dir", default="results")
    args = parser.parse_args()

    try:
        conn = psycopg2.connect(args.dsn)
        conn.autocommit = True
    except psycopg2.OperationalError as exc:
        print(json.dumps({"error": str(exc), "status": "connection_failed"}), file=sys.stderr)
        sys.exit(1)

    snapshots = []
    start = time.monotonic()
    deadline = start + args.duration if args.duration > 0 else start + 1

    try:
        while True:
            snap = sample(conn, args.table, args.new_column)
            snapshots.append(snap)
            print(
                f"[{snap['ts']}] migrated={snap['migrated_rows']} "
                f"remaining={snap['remaining_rows']} ({snap['pct_migrated']}%)",
                file=sys.stderr,
            )

            if snap["remaining_rows"] == 0:
                print("Backfill complete.", file=sys.stderr)
                break
            if args.duration > 0 and time.monotonic() >= deadline:
                break
            if args.duration == 0:
                break

            time.sleep(args.interval)
    finally:
        conn.close()

    result = {
        "scenario": args.scenario,
        "table": args.table,
        "old_column": args.old_column,
        "new_column": args.new_column,
        "poll_interval_s": args.interval,
        "snapshots": snapshots,
        "status": "success",
    }

    print(json.dumps(result, indent=2))

    out_dir = Path(args.results_dir) / args.scenario
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "column_reads.json"
    with open(out_path, "w") as fh:
        json.dump(result, fh, indent=2)
    print(f"\nSaved to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
