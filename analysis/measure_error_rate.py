#!/usr/bin/env python3
"""
measure_error_rate.py

Sends HTTP traffic to users-v1 (port 8001) and users-v2 (port 8002) for a
configurable duration at a fixed request rate, then records error rates and
latency percentiles as JSON.

Usage:
    python measure_error_rate.py \
        --scenario 01_rename_field \
        --duration 60 \
        [--rps 10] \
        [--v1-base-url http://localhost:8001] \
        [--v2-base-url http://localhost:8002]
"""

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import threading
import statistics

try:
    import requests
except ImportError:
    print("requests library required: pip install requests", file=sys.stderr)
    sys.exit(1)

V1_BASE = os.environ.get("V1_BASE_URL", "http://localhost:8001")
V2_BASE = os.environ.get("V2_BASE_URL", "http://localhost:8002")

SAMPLE_USER_IDS = list(range(1, 21))  # IDs 1-20 assumed to exist


def classify_status(code: int) -> str:
    if 200 <= code < 300:
        return "2xx"
    if 400 <= code < 500:
        return "4xx"
    if 500 <= code < 600:
        return "5xx"
    return "other"


def worker(
    version: str,
    base_url: str,
    stop_event: threading.Event,
    results: list,
    rps: int,
    lock: threading.Lock,
) -> None:
    """Continuously send requests until stop_event is set."""
    session = requests.Session()
    interval = 1.0 / rps
    uid_cycle = iter(SAMPLE_USER_IDS * 1000)

    while not stop_event.is_set():
        uid = next(uid_cycle)
        url = f"{base_url}/users/{uid}"
        t0 = time.perf_counter()
        try:
            resp = session.get(url, timeout=5)
            latency_ms = (time.perf_counter() - t0) * 1000
            record = {
                "version": version,
                "status_code": resp.status_code,
                "status_class": classify_status(resp.status_code),
                "latency_ms": round(latency_ms, 2),
                "ts": time.time(),
            }
        except requests.RequestException as exc:
            latency_ms = (time.perf_counter() - t0) * 1000
            record = {
                "version": version,
                "status_code": 0,
                "status_class": "error",
                "latency_ms": round(latency_ms, 2),
                "error": str(exc),
                "ts": time.time(),
            }
        with lock:
            results.append(record)

        elapsed = time.perf_counter() - t0
        sleep_for = interval - elapsed
        if sleep_for > 0:
            time.sleep(sleep_for)


def percentile(data: list[float], pct: float) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = int(len(sorted_data) * pct / 100)
    idx = min(idx, len(sorted_data) - 1)
    return round(sorted_data[idx], 2)


def summarise(records: list, version: str) -> dict:
    version_records = [r for r in records if r["version"] == version]
    if not version_records:
        return {"version": version, "total_requests": 0}

    counts = defaultdict(int)
    latencies = []
    for r in version_records:
        counts[r["status_class"]] += 1
        latencies.append(r["latency_ms"])

    total = len(version_records)
    error_count = counts["4xx"] + counts["5xx"] + counts["error"]
    return {
        "version": version,
        "total_requests": total,
        "status_counts": dict(counts),
        "error_rate_pct": round(error_count / total * 100, 3),
        "latency_p50_ms": percentile(latencies, 50),
        "latency_p95_ms": percentile(latencies, 95),
        "latency_p99_ms": percentile(latencies, 99),
        "latency_mean_ms": round(statistics.mean(latencies), 2),
        "latency_max_ms": round(max(latencies), 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure HTTP error rate during migration")
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--duration", type=int, default=60, help="Test duration in seconds")
    parser.add_argument("--rps", type=int, default=10, help="Requests per second per version")
    parser.add_argument("--v1-base-url", default=V1_BASE)
    parser.add_argument("--v2-base-url", default=V2_BASE)
    parser.add_argument("--results-dir", default="results")
    args = parser.parse_args()

    results: list = []
    lock = threading.Lock()
    stop_event = threading.Event()

    threads = [
        threading.Thread(target=worker, args=("v1", args.v1_base_url, stop_event, results, args.rps, lock), daemon=True),
        threading.Thread(target=worker, args=("v2", args.v2_base_url, stop_event, results, args.rps, lock), daemon=True),
    ]

    print(f"Starting load: {args.rps} rps/version for {args.duration}s ...", file=sys.stderr)
    start_time = datetime.now(timezone.utc)
    for t in threads:
        t.start()

    time.sleep(args.duration)
    stop_event.set()
    for t in threads:
        t.join(timeout=10)

    summary = {
        "scenario": args.scenario,
        "measured_at": start_time.isoformat(),
        "duration_s": args.duration,
        "rps_per_version": args.rps,
        "v1": summarise(results, "v1"),
        "v2": summarise(results, "v2"),
        "combined": {
            "total_requests": len(results),
            "error_rate_pct": round(
                sum(1 for r in results if r["status_class"] not in ("2xx",)) / max(len(results), 1) * 100, 3
            ),
        },
        "status": "success",
    }

    print(json.dumps(summary, indent=2))

    out_dir = Path(args.results_dir) / args.scenario
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "error_rate.json"
    with open(out_path, "w") as fh:
        json.dump(summary, fh, indent=2)
    print(f"\nSaved to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
