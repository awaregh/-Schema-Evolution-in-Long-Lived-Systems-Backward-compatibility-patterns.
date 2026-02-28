#!/usr/bin/env python3
"""
compat/checks/check_event_compat.py
=====================================
CLI tool: check backward-compatibility between two JSON Schema event files.

Usage
-----
    python check_event_compat.py <old_schema.json> <new_schema.json>

Exit codes
----------
    0  – all rules passed (warnings printed but do not cause failure)
    1  – one or more rules failed, or a file could not be read
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from compat.rules.event_compat_rules import run_all_checks  # noqa: E402

# ---------------------------------------------------------------------------
# ANSI colour helpers
# ---------------------------------------------------------------------------

def _supports_colour() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


_COLOURS = {
    "red":    "\033[31m",
    "yellow": "\033[33m",
    "green":  "\033[32m",
    "bold":   "\033[1m",
    "reset":  "\033[0m",
}


def _colour(text: str, *codes: str) -> str:
    if not _supports_colour():
        return text
    prefix = "".join(_COLOURS.get(c, "") for c in codes)
    return f"{prefix}{text}{_COLOURS['reset']}"


_STATUS_LABELS = {
    "pass": ("[PASS]", ("green",)),
    "warn": ("[WARN]", ("yellow", "bold")),
    "fail": ("[FAIL]", ("red", "bold")),
}


def _render_status(status: str) -> str:
    label, colours = _STATUS_LABELS.get(status, ("[????]", ()))
    return _colour(label, *colours)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]

    if len(args) < 2:
        print(
            _colour("Usage: check_event_compat.py <old_schema.json> <new_schema.json>", "bold"),
            file=sys.stderr,
        )
        return 1

    old_path, new_path = args[0], args[1]

    for path in (old_path, new_path):
        if not os.path.isfile(path):
            print(
                _colour(f"ERROR: File not found: '{path}'", "red", "bold"),
                file=sys.stderr,
            )
            return 1

    print(_colour("\nEvent Schema Compatibility Check", "bold"))
    print(_colour(f"  OLD: {old_path}", ""))
    print(_colour(f"  NEW: {new_path}", ""))
    print("-" * 60)

    try:
        results = run_all_checks(old_path, new_path)
    except Exception as exc:  # noqa: BLE001
        print(
            _colour(f"ERROR: Failed to parse schemas: {exc}", "red", "bold"),
            file=sys.stderr,
        )
        return 1

    has_failures = False
    has_warnings = False

    for result in results:
        status = result["status"]
        label  = _render_status(status)
        rule   = _colour(result["rule"], "bold")
        msg    = result["message"]
        print(f"{label}  {rule}")
        for line in msg.splitlines():
            print(f"       {line}")
        print()

        if status == "fail":
            has_failures = True
        elif status == "warn":
            has_warnings = True

    print("-" * 60)

    if has_failures:
        print(_colour(
            "RESULT: FAILED – event schema changes are not backward-compatible.",
            "red", "bold",
        ))
        return 1

    if has_warnings:
        print(_colour(
            "RESULT: PASSED with warnings – review above before deploying.",
            "yellow", "bold",
        ))
        return 0

    print(_colour(
        "RESULT: PASSED – event schema changes are backward-compatible.",
        "green", "bold",
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
