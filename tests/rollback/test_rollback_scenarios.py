"""
tests/rollback/test_rollback_scenarios.py
==========================================
Tests for Expand-Contract rollback scenarios.

These tests simulate the database / service layer with plain Python dicts
so no real database is required.

Scenarios covered:
  - v1 service reads v2 data rows (tolerant reader)
  - v2 service reads v1 data rows (backward compat)
  - Dual-write keeps both column sets in sync
  - Safe rollback to v1 after the Expand phase
"""

from __future__ import annotations

import copy
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytest

# ---------------------------------------------------------------------------
# Simulated database table (list of row dicts)
# ---------------------------------------------------------------------------

def _make_row_v1(
    first_name: str = "Jane",
    last_name: str = "Doe",
    email: str = "jane@example.com",
) -> Dict[str, Any]:
    """Create a row as stored by a v1 service (old columns only)."""
    return {
        "id":         str(uuid.uuid4()),
        "first_name": first_name,
        "last_name":  last_name,
        "email":      email,
        "status":     "active",
        "plan":       "free",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        # v2 columns absent in rows written by the old service
        "given_name":  None,
        "family_name": None,
    }


def _make_row_v2(
    given_name: str = "Jane",
    family_name: str = "Doe",
    email: str = "jane@example.com",
) -> Dict[str, Any]:
    """Create a row as stored by a v2 service (both old and new columns)."""
    return {
        "id":          str(uuid.uuid4()),
        "given_name":  given_name,
        "family_name": family_name,
        # deprecated aliases kept in sync (dual-write)
        "first_name":  given_name,
        "last_name":   family_name,
        "email":       email,
        "status":      "active",
        "plan":        "free",
        "created_at":  datetime.now(timezone.utc).isoformat(),
        "updated_at":  datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Simulated service read models
# ---------------------------------------------------------------------------

class UserServiceV1:
    """
    A v1 service that reads first_name / last_name.
    Implements tolerant reader: ignores unknown columns.
    """

    def read_user(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id":         row["id"],
            "first_name": row["first_name"],
            "last_name":  row["last_name"],
            "email":      row["email"],
            "status":     row.get("status"),
            "plan":       row.get("plan"),
        }


class UserServiceV2:
    """
    A v2 service that reads given_name / family_name.
    Falls back to first_name / last_name when new columns are absent (NULL).
    """

    def read_user(self, row: Dict[str, Any]) -> Dict[str, Any]:
        given_name  = row.get("given_name")  or row.get("first_name")
        family_name = row.get("family_name") or row.get("last_name")
        return {
            "id":          row["id"],
            "given_name":  given_name,
            "family_name": family_name,
            "email":       row["email"],
            "status":      row.get("status"),
            "plan":        row.get("plan"),
        }

    def write_user(
        self,
        given_name: str,
        family_name: str,
        email: str,
        existing_row: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Dual-write: populate both old and new columns."""
        now = datetime.now(timezone.utc).isoformat()
        row_id = existing_row["id"] if existing_row else str(uuid.uuid4())
        created_at = existing_row["created_at"] if existing_row else now
        return {
            "id":          row_id,
            "given_name":  given_name,
            "family_name": family_name,
            "first_name":  given_name,    # dual-write deprecated alias
            "last_name":   family_name,   # dual-write deprecated alias
            "email":       email,
            "status":      existing_row["status"] if existing_row else "pending",
            "plan":        existing_row["plan"] if existing_row else "free",
            "created_at":  created_at,
            "updated_at":  now,
        }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTolerantReader:

    def test_v1_service_reads_v2_data(self):
        """
        A v1 service using tolerant reader can process a row written by v2.
        It ignores given_name / family_name and reads first_name / last_name.
        """
        row_v2  = _make_row_v2("Alice", "Smith")
        service = UserServiceV1()
        result  = service.read_user(row_v2)

        assert result["first_name"] == "Alice"
        assert result["last_name"]  == "Smith"
        assert result["email"]      == row_v2["email"]
        assert "given_name"  not in result
        assert "family_name" not in result

    def test_v1_service_ignores_new_columns(self):
        """Extra v2 columns must not surface in the v1 service's output."""
        row_v2  = _make_row_v2("Bob", "Jones")
        service = UserServiceV1()
        result  = service.read_user(row_v2)

        extra_v2_keys = {"given_name", "family_name", "display_name", "locale"}
        assert extra_v2_keys.isdisjoint(result.keys())


class TestV2ReadingV1Data:

    def test_v2_service_reads_v1_data(self):
        """
        A v2 service falls back to first_name / last_name when given_name /
        family_name columns are NULL (rows written before v2 migration).
        """
        row_v1  = _make_row_v1("Carol", "White")
        service = UserServiceV2()
        result  = service.read_user(row_v1)

        # v2 service must expose canonical fields populated from aliases
        assert result["given_name"]  == "Carol"
        assert result["family_name"] == "White"

    def test_v2_service_prefers_canonical_over_alias(self):
        """
        When a row has both canonical (given_name) and alias (first_name),
        the canonical field must take precedence.
        """
        row = _make_row_v2("Diana", "Prince")
        row["first_name"] = "Di"  # mismatched alias (should be ignored)
        service = UserServiceV2()
        result  = service.read_user(row)

        assert result["given_name"] == "Diana"  # canonical wins


class TestDualWrite:

    def test_dual_write_consistency(self):
        """
        When v2 service writes a row, both the canonical columns (given_name /
        family_name) and the deprecated aliases (first_name / last_name) must
        carry the same value.
        """
        service = UserServiceV2()
        row = service.write_user("Eve", "Green", "eve@example.com")

        assert row["given_name"]  == row["first_name"],  "given_name and first_name must match"
        assert row["family_name"] == row["last_name"],   "family_name and last_name must match"

    def test_dual_write_update_keeps_columns_in_sync(self):
        """Updating an existing row via dual-write keeps both column sets consistent."""
        existing = _make_row_v2("Frank", "Blue")
        service  = UserServiceV2()

        updated = service.write_user("Frank", "Red", existing["email"], existing_row=existing)

        assert updated["given_name"]  == "Frank"
        assert updated["family_name"] == "Red"
        assert updated["first_name"]  == "Frank"
        assert updated["last_name"]   == "Red"
        # ID and created_at unchanged
        assert updated["id"]         == existing["id"]
        assert updated["created_at"] == existing["created_at"]

    def test_dual_write_both_columns_readable_by_v1(self):
        """Rows written by v2 must still be readable by a v1 service."""
        service_v2 = UserServiceV2()
        service_v1 = UserServiceV1()

        row    = service_v2.write_user("Grace", "Hopper", "grace@example.com")
        result = service_v1.read_user(row)

        assert result["first_name"] == "Grace"
        assert result["last_name"]  == "Hopper"


class TestRollback:

    def test_rollback_to_v1_after_expand(self):
        """
        After the Expand phase, if we roll back to v1, the v1 service should
        still read correct data from the alias columns (which v2 kept in sync).

        Scenario:
          1. v2 service writes rows with dual-write.
          2. Rollback occurs: v2 service goes offline, v1 service resumes.
          3. v1 service reads the rows – must get valid first_name / last_name.
        """
        service_v2 = UserServiceV2()
        service_v1 = UserServiceV1()

        # v2 writes several rows
        rows = [
            service_v2.write_user("Alice", "Smith", "alice@example.com"),
            service_v2.write_user("Bob",   "Jones", "bob@example.com"),
            service_v2.write_user("Carol", "White", "carol@example.com"),
        ]

        # Rollback: v1 service reads all rows
        for row in rows:
            result = service_v1.read_user(row)
            assert result["first_name"], "first_name must not be empty after rollback"
            assert result["last_name"],  "last_name must not be empty after rollback"
            assert "@" in result["email"]

    def test_v1_writes_after_rollback_dont_break_schema(self):
        """
        After rollback, v1 writes only update first_name / last_name.
        The new given_name / family_name columns are left NULL.
        This is acceptable during the Expand phase – the next v2 deploy
        will back-fill them.
        """
        # Simulate v1 write (only knows about old columns)
        v1_written_row = _make_row_v1("David", "Black")
        assert v1_written_row["given_name"]  is None
        assert v1_written_row["family_name"] is None

        # v2 service can still read it via fallback
        service_v2 = UserServiceV2()
        result = service_v2.read_user(v1_written_row)

        assert result["given_name"]  == "David"
        assert result["family_name"] == "Black"

    def test_mixed_row_versions_in_same_table(self):
        """
        During the migration window the table contains both v1 rows (NULL new
        columns) and v2 rows (all columns populated).  Both service versions
        must handle the full mixed set without error.
        """
        rows: List[Dict[str, Any]] = [
            _make_row_v1("Earl",  "Grey"),    # written by v1 – NULL new cols
            _make_row_v2("Fiona", "Apple"),   # written by v2 – all cols set
            _make_row_v1("Gary",  "Oak"),     # another v1 row
        ]

        service_v1 = UserServiceV1()
        service_v2 = UserServiceV2()

        for row in rows:
            r1 = service_v1.read_user(row)
            r2 = service_v2.read_user(row)

            assert r1["first_name"]
            assert r1["last_name"]
            assert r2["given_name"]
            assert r2["family_name"]
