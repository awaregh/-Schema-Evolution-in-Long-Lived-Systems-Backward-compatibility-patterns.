#!/usr/bin/env python3
"""
compat/checks/check_db_migration.py
=====================================
CLI tool: validate a SQL migration file against backward-compatibility rules.

Usage
-----
    python check_db_migration.py <migration_file.sql>

Exit codes
----------
    0  – all rules passed (warnings are printed but do not fail)
    1  – one or more rules failed, or the file could not be read
"""

from __future__ import annotations

import sys
import os

# Allow running from any directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from compat.rules.db_migration_rules import run_all_checks  # noqa: E402

# ---------------------------------------------------------------------------
# Terminal colour helpers (gracefully degrade when ANSI not supported)
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


# ---------------------------------------------------------------------------
# Status rendering
# ---------------------------------------------------------------------------

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

    if not args:
        print(
            _colour("Usage: check_db_migration.py <migration_file.sql>", "bold"),
            file=sys.stderr,
        )
        return 1

    migration_file = args[0]

    try:
        with open(migration_file, "r", encoding="utf-8") as fh:
            sql = fh.read()
    except OSError as exc:
        print(
            _colour(f"ERROR: Cannot read '{migration_file}': {exc}", "red", "bold"),
            file=sys.stderr,
        )
        return 1

    print(_colour(f"\nChecking migration: {migration_file}", "bold"))
    print("-" * 60)

    results = run_all_checks(sql)

    has_failures = False
    has_warnings = False

    for result in results:
        status = result["status"]
        label  = _render_status(status)
        rule   = _colour(result["rule"], "bold")
        msg    = result["message"]
        print(f"{label}  {rule}")
        print(f"       {msg}")
        print()

        if status == "fail":
            has_failures = True
        elif status == "warn":
            has_warnings = True

    print("-" * 60)

    if has_failures:
        summary = _colour("RESULT: FAILED – migration has compatibility violations.", "red", "bold")
        print(summary)
        return 1

    if has_warnings:
        summary = _colour(
            "RESULT: PASSED with warnings – review the warnings above before proceeding.",
            "yellow", "bold",
        )
        print(summary)
        return 0

    print(_colour("RESULT: PASSED – no issues found.", "green", "bold"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
