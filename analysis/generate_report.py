#!/usr/bin/env python3
"""
generate_report.py

Reads all result JSON files from results/ and generates a Markdown summary
report at results/summary_report.md.

Usage:
    python generate_report.py [--results-dir results]
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


SCENARIO_NAMES = {
    "01_rename_field": "Rename Field (first_name → given_name)",
    "02_split_column": "Split Column (name → first_name + last_name)",
    "03_type_change": "Type Change (amount_cents int → amount decimal)",
    "04_add_not_null": "Add NOT NULL Column with Default",
    "05_remove_field": "Remove Field (with deprecation strategy)",
    "06_new_event_field": "New Event Field with Old Consumer",
    "07_dual_consumer": "Two Consumer Versions Running Simultaneously",
    "08_denormalization": "Denormalization / Normalization Change",
}


def load_json(path: Path) -> dict | None:
    try:
        with open(path) as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


def fmt_float(val, suffix="") -> str:
    if val is None:
        return "N/A"
    return f"{val}{suffix}"


def render_migration_time(data: dict) -> str:
    if not data:
        return "_No data_"
    m = data.get("migration", {})
    lines = [
        f"- **Wall clock:** {fmt_float(m.get('wall_clock_s'), 's')}",
        f"- **Rows affected:** {m.get('total_rows_affected', 'N/A')}",
        f"- **Time per 1k rows:** {fmt_float(m.get('time_per_1k_rows_s'), 's')}",
        f"- **Is backfill:** {m.get('is_backfill', False)}",
    ]
    return "\n".join(lines)


def render_error_rate(data: dict) -> str:
    if not data:
        return "_No data_"
    v1 = data.get("v1", {})
    v2 = data.get("v2", {})
    combined = data.get("combined", {})
    lines = [
        f"| Version | Requests | Error Rate | p50 (ms) | p95 (ms) | p99 (ms) |",
        f"|---------|----------|------------|----------|----------|----------|",
        f"| v1 | {v1.get('total_requests','N/A')} | {fmt_float(v1.get('error_rate_pct'),'%')} | {fmt_float(v1.get('latency_p50_ms'))} | {fmt_float(v1.get('latency_p95_ms'))} | {fmt_float(v1.get('latency_p99_ms'))} |",
        f"| v2 | {v2.get('total_requests','N/A')} | {fmt_float(v2.get('error_rate_pct'),'%')} | {fmt_float(v2.get('latency_p50_ms'))} | {fmt_float(v2.get('latency_p95_ms'))} | {fmt_float(v2.get('latency_p99_ms'))} |",
        f"| **combined** | {combined.get('total_requests','N/A')} | **{fmt_float(combined.get('error_rate_pct'),'%')}** | — | — | — |",
    ]
    return "\n".join(lines)


def render_column_reads(data: dict) -> str:
    if not data:
        return "_No data_"
    snapshots = data.get("snapshots", [])
    if not snapshots:
        return "_No snapshots recorded_"
    last = snapshots[-1]
    lines = [
        f"- **Snapshots recorded:** {len(snapshots)}",
        f"- **Final % migrated:** {last.get('pct_migrated', 'N/A')}%",
        f"- **Remaining rows at end:** {last.get('remaining_rows', 'N/A')}",
    ]
    return "\n".join(lines)


def generate_report(results_dir: Path) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sections = [
        f"# Schema Evolution – Summary Report\n\n_Generated: {now}_\n",
        "## Overview\n",
        "This report aggregates measurements from all eight schema-evolution scenarios.\n",
        "---\n",
    ]

    metrics_table_rows = []

    for scenario_dir in sorted(results_dir.iterdir()):
        if not scenario_dir.is_dir():
            continue
        scenario = scenario_dir.name
        label = SCENARIO_NAMES.get(scenario, scenario)

        mt = load_json(scenario_dir / "migration_time.json")
        er = load_json(scenario_dir / "error_rate.json")
        cr = load_json(scenario_dir / "column_reads.json")

        section = [
            f"## {scenario}: {label}\n",
            "### Migration Time\n",
            render_migration_time(mt),
            "\n### Error Rate\n",
            render_error_rate(er),
            "\n### Column Backfill Progress\n",
            render_column_reads(cr),
            "\n---\n",
        ]
        sections.extend(section)

        # Collect summary table row
        wall = mt.get("migration", {}).get("wall_clock_s") if mt else None
        err_rate = er.get("combined", {}).get("error_rate_pct") if er else None
        metrics_table_rows.append((scenario, label, wall, err_rate))

    # Append metrics comparison table
    sections.append("## Metrics Comparison\n")
    sections.append("| Scenario | Migration Time (s) | Error Rate (%) |")
    sections.append("|----------|--------------------|----------------|")
    for scenario, label, wall, err in metrics_table_rows:
        sections.append(f"| {scenario} | {fmt_float(wall)} | {fmt_float(err)} |")

    return "\n".join(sections) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Markdown summary report")
    parser.add_argument("--results-dir", default="results")
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    if not results_dir.exists():
        print(f"Results directory not found: {results_dir}", file=sys.stderr)
        raise SystemExit(1)

    report = generate_report(results_dir)
    out_path = results_dir / "summary_report.md"
    with open(out_path, "w") as fh:
        fh.write(report)

    print(report)
    print(f"\nReport saved to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    import sys
    main()
