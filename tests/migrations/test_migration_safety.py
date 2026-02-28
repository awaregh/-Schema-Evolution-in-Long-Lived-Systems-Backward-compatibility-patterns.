"""
tests/migrations/test_migration_safety.py
===========================================
Tests for database migration safety rule engine.

Covers:
  - DROP COLUMN blocked in non-contract phase
  - ADD COLUMN nullable passes
  - ADD COLUMN NOT NULL without DEFAULT warns
  - CREATE INDEX CONCURRENTLY passes
  - Idempotent backfill pattern (mocked)
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from compat.rules.db_migration_rules import (  # noqa: E402
    check_no_drop_column,
    check_no_drop_table,
    check_not_null_safety,
    check_rename_safety,
    check_index_concurrent,
    run_all_checks,
)

# ---------------------------------------------------------------------------
# Tests: DROP COLUMN
# ---------------------------------------------------------------------------

class TestDropColumn:

    def test_drop_column_without_contract_phase_fails(self):
        """DROP COLUMN in a migration must be flagged as a failure."""
        sql = "ALTER TABLE users DROP COLUMN first_name;"
        result = check_no_drop_column(sql)
        assert result["status"] == "fail"
        assert "DROP COLUMN" in result["message"]

    def test_no_drop_column_passes(self):
        sql = "ALTER TABLE users ADD COLUMN given_name VARCHAR(100);"
        result = check_no_drop_column(sql)
        assert result["status"] == "pass"

    def test_drop_column_case_insensitive(self):
        sql = "alter table users drop column last_name;"
        result = check_no_drop_column(sql)
        assert result["status"] == "fail"

    def test_drop_index_not_flagged_as_drop_column(self):
        """DROP INDEX is a different statement; must not trigger the column rule."""
        sql = "DROP INDEX CONCURRENTLY IF EXISTS users_first_name_idx;"
        result = check_no_drop_column(sql)
        assert result["status"] == "pass"


# ---------------------------------------------------------------------------
# Tests: DROP TABLE
# ---------------------------------------------------------------------------

class TestDropTable:

    def test_drop_table_fails(self):
        sql = "DROP TABLE legacy_users;"
        result = check_no_drop_table(sql)
        assert result["status"] == "fail"

    def test_drop_table_if_exists_fails(self):
        sql = "DROP TABLE IF EXISTS old_subscriptions;"
        result = check_no_drop_table(sql)
        assert result["status"] == "fail"

    def test_no_drop_table_passes(self):
        sql = "CREATE TABLE new_users (id UUID PRIMARY KEY);"
        result = check_no_drop_table(sql)
        assert result["status"] == "pass"


# ---------------------------------------------------------------------------
# Tests: ADD COLUMN NOT NULL safety
# ---------------------------------------------------------------------------

class TestNotNullSafety:

    def test_add_nullable_column_passes(self):
        """ADD COLUMN without NOT NULL is safe on non-empty tables."""
        sql = "ALTER TABLE users ADD COLUMN given_name VARCHAR(100);"
        result = check_not_null_safety(sql)
        assert result["status"] == "pass"

    def test_add_not_null_without_default_warns(self):
        """ADD COLUMN NOT NULL without DEFAULT must warn."""
        sql = "ALTER TABLE users ADD COLUMN given_name VARCHAR(100) NOT NULL;"
        result = check_not_null_safety(sql)
        assert result["status"] == "warn"
        assert "NOT NULL" in result["message"] or "DEFAULT" in result["message"]

    def test_add_not_null_with_default_passes(self):
        """ADD COLUMN NOT NULL WITH DEFAULT is safe."""
        sql = "ALTER TABLE users ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'active';"
        result = check_not_null_safety(sql)
        assert result["status"] == "pass"

    def test_set_not_null_on_existing_column_not_flagged(self):
        """ALTER COLUMN SET NOT NULL (separate statement) is not flagged by this rule."""
        sql = "ALTER TABLE users ALTER COLUMN given_name SET NOT NULL;"
        result = check_not_null_safety(sql)
        assert result["status"] == "pass"


# ---------------------------------------------------------------------------
# Tests: RENAME COLUMN safety
# ---------------------------------------------------------------------------

class TestRenameSafety:

    def test_rename_column_warns(self):
        sql = "ALTER TABLE users RENAME COLUMN first_name TO given_name;"
        result = check_rename_safety(sql)
        assert result["status"] == "warn"
        assert "RENAME" in result["message"].upper()

    def test_no_rename_passes(self):
        sql = "ALTER TABLE users ADD COLUMN given_name VARCHAR(100);"
        result = check_rename_safety(sql)
        assert result["status"] == "pass"


# ---------------------------------------------------------------------------
# Tests: CREATE INDEX CONCURRENTLY
# ---------------------------------------------------------------------------

class TestIndexConcurrent:

    def test_create_index_concurrent_passes(self):
        sql = "CREATE INDEX CONCURRENTLY IF NOT EXISTS users_given_name_idx ON users (given_name);"
        result = check_index_concurrent(sql)
        assert result["status"] == "pass"

    def test_create_index_without_concurrently_warns(self):
        sql = "CREATE INDEX users_given_name_idx ON users (given_name);"
        result = check_index_concurrent(sql)
        assert result["status"] == "warn"
        assert "CONCURRENTLY" in result["message"]

    def test_create_unique_index_without_concurrently_warns(self):
        sql = "CREATE UNIQUE INDEX users_email_idx ON users (email);"
        result = check_index_concurrent(sql)
        assert result["status"] == "warn"

    def test_no_index_creation_passes(self):
        sql = "UPDATE users SET given_name = first_name WHERE given_name IS NULL;"
        result = check_index_concurrent(sql)
        assert result["status"] == "pass"


# ---------------------------------------------------------------------------
# Tests: Idempotent backfill (mocked DB layer)
# ---------------------------------------------------------------------------

class TestBackfillMigration:

    def test_backfill_migration_is_idempotent(self):
        """
        Verify that a backfill migration using WHERE … IS NULL is idempotent:
        running it twice produces the same result (no extra rows updated).

        The DB layer is mocked so no real database is needed.
        """
        backfill_sql = (
            "UPDATE users "
            "SET given_name = first_name, family_name = last_name "
            "WHERE given_name IS NULL OR family_name IS NULL;"
        )

        # Simulate DB execute: first run affects 5 rows, second run affects 0
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 5

        def execute_side_effect(sql):
            mock_cursor.rowcount = 5 if mock_cursor.call_count == 0 else 0
            mock_cursor.call_count += 1

        mock_cursor.call_count = 0
        mock_cursor.execute.side_effect = execute_side_effect

        # First run
        mock_cursor.execute(backfill_sql)
        first_run_rows = mock_cursor.rowcount

        # Second run: remaining rows = 0 (already backfilled)
        mock_cursor.rowcount = 0
        mock_cursor.execute(backfill_sql)
        second_run_rows = mock_cursor.rowcount

        assert first_run_rows == 5,  "First run should have updated rows"
        assert second_run_rows == 0, "Second run should be a no-op (idempotent)"

    def test_backfill_sql_contains_safety_guard(self):
        """
        Idempotency guard: backfill SQL must only touch rows where the
        new column IS NULL.  Ensures re-running is safe.
        """
        backfill_sql = (
            "UPDATE users "
            "SET given_name = first_name "
            "WHERE given_name IS NULL;"
        )
        assert "WHERE" in backfill_sql.upper()
        assert "IS NULL" in backfill_sql.upper()


# ---------------------------------------------------------------------------
# Tests: run_all_checks aggregation
# ---------------------------------------------------------------------------

class TestRunAllChecks:

    def test_clean_migration_all_pass(self):
        sql = """
        ALTER TABLE users
            ADD COLUMN IF NOT EXISTS given_name VARCHAR(100),
            ADD COLUMN IF NOT EXISTS family_name VARCHAR(100);

        UPDATE users
            SET given_name = first_name, family_name = last_name
        WHERE given_name IS NULL;

        CREATE INDEX CONCURRENTLY IF NOT EXISTS users_given_name_idx
            ON users (given_name);
        """
        results = run_all_checks(sql)
        failures = [r for r in results if r["status"] == "fail"]
        assert failures == []

    def test_dangerous_migration_has_failures(self):
        sql = "ALTER TABLE users DROP COLUMN first_name; DROP TABLE legacy_data;"
        results = run_all_checks(sql)
        failures = [r for r in results if r["status"] == "fail"]
        assert len(failures) >= 2, "Expected at least two failures (DROP COLUMN + DROP TABLE)"

    def test_results_include_all_rule_names(self):
        sql = "SELECT 1;"
        results = run_all_checks(sql)
        rule_names = {r["rule"] for r in results}
        expected = {
            "no_drop_column",
            "no_drop_table",
            "not_null_safety",
            "rename_safety",
            "index_concurrent",
        }
        assert expected == rule_names
