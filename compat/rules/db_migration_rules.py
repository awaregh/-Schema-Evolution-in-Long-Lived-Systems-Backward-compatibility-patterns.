"""
compat/rules/db_migration_rules.py
===================================
Rules for validating database migration SQL for backward-compatibility safety.

Each rule function accepts a migration SQL string and returns a result dict:

    {
        "rule":    "<rule name>",
        "status":  "pass" | "warn" | "fail",
        "message": "<human-readable description>",
    }

``run_all_checks`` runs every rule and returns a list of result dicts.
"""

from __future__ import annotations

import re
from typing import Dict, List

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

RuleResult = Dict[str, str]


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _normalise(sql: str) -> str:
    """Return SQL collapsed to upper-case single-spaced text, comments stripped."""
    # Remove single-line comments
    sql = re.sub(r"--[^\n]*", " ", sql)
    # Remove block comments
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    # Collapse whitespace
    return re.sub(r"\s+", " ", sql).upper()


def _contains(pattern: str, sql: str, flags: int = 0) -> bool:
    return bool(re.search(pattern, sql, flags | re.IGNORECASE))


# ---------------------------------------------------------------------------
# Individual rules
# ---------------------------------------------------------------------------

def check_no_drop_column(migration_sql: str) -> RuleResult:
    """
    Fail if a DROP COLUMN statement is present.

    Dropping a column is a destructive, non-backward-compatible change.
    It must only appear in the *Contract* phase after all services have
    migrated away from reading that column.
    """
    norm = _normalise(migration_sql)
    if re.search(r"\bDROP\s+COLUMN\b", norm):
        return {
            "rule": "no_drop_column",
            "status": "fail",
            "message": (
                "DROP COLUMN detected.  Dropping a column breaks backward "
                "compatibility.  Use the Expand-Contract pattern: first deprecate "
                "the column and remove it only after all consumers have migrated."
            ),
        }
    return {
        "rule": "no_drop_column",
        "status": "pass",
        "message": "No DROP COLUMN found.",
    }


def check_no_drop_table(migration_sql: str) -> RuleResult:
    """
    Fail if a DROP TABLE statement is present.

    Dropping a table is irreversible and breaks any service that still
    references it.
    """
    norm = _normalise(migration_sql)
    if re.search(r"\bDROP\s+TABLE\b", norm):
        return {
            "rule": "no_drop_table",
            "status": "fail",
            "message": (
                "DROP TABLE detected.  Dropping a table breaks backward "
                "compatibility and is irreversible.  Archive data before removal "
                "and ensure no service reads from this table."
            ),
        }
    return {
        "rule": "no_drop_table",
        "status": "pass",
        "message": "No DROP TABLE found.",
    }


def check_not_null_safety(migration_sql: str) -> RuleResult:
    """
    Warn if ADD COLUMN … NOT NULL appears without a DEFAULT clause.

    Adding a NOT NULL column without a DEFAULT fails immediately on a
    non-empty table.  Either supply a DEFAULT, or add the column as
    NULLable first, back-fill, then add the constraint.
    """
    norm = _normalise(migration_sql)
    # Capture each ADD COLUMN definition up to the next semicolon or
    # statement boundary so that DEFAULT appearing after NOT NULL is included.
    add_col_pattern = re.compile(
        r"ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?\S+[^;]*",
        re.IGNORECASE,
    )
    for match in add_col_pattern.finditer(norm):
        segment = match.group(0).upper()
        if "NOT NULL" in segment and "DEFAULT" not in segment:
            return {
                "rule": "not_null_safety",
                "status": "warn",
                "message": (
                    "ADD COLUMN … NOT NULL without DEFAULT detected.  This will "
                    "fail on a non-empty table.  Add a DEFAULT value or make the "
                    "column nullable first, back-fill, then add the NOT NULL "
                    "constraint in a separate migration."
                ),
            }
    return {
        "rule": "not_null_safety",
        "status": "pass",
        "message": "No unsafe NOT NULL column additions found.",
    }


def check_rename_safety(migration_sql: str) -> RuleResult:
    """
    Warn if ALTER TABLE … RENAME COLUMN is present.

    Renaming a column breaks any service that still references the old
    name.  Use the Expand-Contract pattern instead: add the new column,
    dual-write, migrate readers, then drop the old column.
    """
    norm = _normalise(migration_sql)
    if re.search(r"\bRENAME\s+COLUMN\b", norm):
        return {
            "rule": "rename_safety",
            "status": "warn",
            "message": (
                "RENAME COLUMN detected.  Renaming a column is not backward-"
                "compatible.  Use Expand-Contract: add the new column, copy data, "
                "update all consumers, then drop the old column."
            ),
        }
    return {
        "rule": "rename_safety",
        "status": "pass",
        "message": "No RENAME COLUMN found.",
    }


def check_index_concurrent(migration_sql: str) -> RuleResult:
    """
    Warn if CREATE INDEX is used without CONCURRENTLY.

    A standard CREATE INDEX takes a full table lock, blocking reads and
    writes for the duration.  In production always use
    CREATE INDEX CONCURRENTLY.
    """
    norm = _normalise(migration_sql)
    # Find all CREATE INDEX statements
    for match in re.finditer(r"\bCREATE\s+(UNIQUE\s+)?INDEX\b", norm):
        # Extract a window of tokens after the keyword
        start = match.start()
        window = norm[start : start + 80]
        if "CONCURRENTLY" not in window:
            return {
                "rule": "index_concurrent",
                "status": "warn",
                "message": (
                    "CREATE INDEX without CONCURRENTLY detected.  This acquires "
                    "a full table lock in production.  Use "
                    "CREATE INDEX CONCURRENTLY to avoid blocking queries."
                ),
            }
    return {
        "rule": "index_concurrent",
        "status": "pass",
        "message": "All index creations use CONCURRENTLY (or no indexes created).",
    }


# ---------------------------------------------------------------------------
# Aggregate runner
# ---------------------------------------------------------------------------

_ALL_RULES = [
    check_no_drop_column,
    check_no_drop_table,
    check_not_null_safety,
    check_rename_safety,
    check_index_concurrent,
]


def run_all_checks(migration_sql: str) -> List[RuleResult]:
    """
    Run every rule against *migration_sql* and return a list of results.

    Results are ordered by rule definition order.  The caller should
    inspect each result's ``status`` field:

    - ``"pass"``  – rule satisfied, no action needed.
    - ``"warn"``  – potential issue; human review recommended.
    - ``"fail"``  – rule violated; migration should be blocked.
    """
    return [rule(migration_sql) for rule in _ALL_RULES]
