"""
tests/contract/test_event_compat.py
=====================================
Tests for event schema evolution and backward compatibility.

Covers:
  - JSON Schema validation of v1 and v2 events
  - Tolerant-reader pattern (v2 event readable by v1 consumer)
  - Upcast (v1 → v2) and downcast (v2 → v1) transformations
  - Rule-level checks for adding required vs optional fields
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import pytest
import jsonschema

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent.parent
EVENTS_DIR = REPO_ROOT / "contracts" / "events"

V1_SCHEMA_PATH = EVENTS_DIR / "user_registered_v1.json"
V2_SCHEMA_PATH = EVENTS_DIR / "user_registered_v2.json"


def _load_schema(path: Path) -> dict:
    with open(path) as fh:
        return json.load(fh)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Upcast / Downcast helpers (units under test)
# ---------------------------------------------------------------------------

def upcast_v1_to_v2(event_v1: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert a v1 user.registered event to v2 format.

    Strategy:
      - Copy all envelope fields unchanged.
      - Map first_name → given_name, last_name → family_name.
      - Retain first_name / last_name as deprecated aliases.
      - Bump event_version to "2.0".
    """
    data = event_v1["data"].copy()
    data["given_name"]  = data["first_name"]
    data["family_name"] = data["last_name"]
    # keep deprecated aliases in place

    return {
        **event_v1,
        "event_version": "2.0",
        "data": data,
    }


def downcast_v2_to_v1(event_v2: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert a v2 user.registered event to v1 format (lossy but safe).

    Strategy:
      - Copy envelope fields, reset event_version to "1.0".
      - Map given_name → first_name, family_name → last_name.
      - Drop v2-only fields (locale, display_name) – acceptable loss.
    """
    data_v2 = event_v2["data"]
    data_v1: Dict[str, Any] = {
        "user_id":    data_v2["user_id"],
        "email":      data_v2["email"],
        "first_name": data_v2.get("first_name") or data_v2["given_name"],
        "last_name":  data_v2.get("last_name")  or data_v2["family_name"],
    }
    if "plan" in data_v2:
        data_v1["plan"] = data_v2["plan"]

    return {
        **event_v2,
        "event_version": "1.0",
        "data": data_v1,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEventSchemaValidation:
    """Validate sample events against their JSON Schemas."""

    def test_v1_event_valid_against_schema(self, sample_event_v1):
        schema = _load_schema(V1_SCHEMA_PATH)
        # Should not raise
        jsonschema.validate(instance=sample_event_v1, schema=schema)

    def test_v2_event_valid_against_schema(self, sample_event_v2):
        schema = _load_schema(V2_SCHEMA_PATH)
        jsonschema.validate(instance=sample_event_v2, schema=schema)

    def test_v1_event_fails_v2_schema_validation(self, sample_event_v1):
        """A raw v1 event is NOT valid against v2 schema (missing given_name)."""
        schema = _load_schema(V2_SCHEMA_PATH)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=sample_event_v1, schema=schema)

    def test_v2_event_missing_required_field_fails(self, sample_event_v2):
        """Removing a required field must fail validation."""
        schema = _load_schema(V2_SCHEMA_PATH)
        bad_event = {**sample_event_v2}
        bad_event["data"] = {k: v for k, v in bad_event["data"].items() if k != "given_name"}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad_event, schema=schema)


class TestTolerantReader:
    """
    v1 consumers applying tolerant-reader pattern can process v2 events
    by reading only the fields they know about (first_name / last_name aliases).
    """

    def test_v2_backward_compat_with_v1_consumer(self, sample_event_v2):
        """
        Simulate a v1 consumer that only reads first_name, last_name, email.
        It should succeed on a v2 event because aliases are present.
        """

        def v1_consumer_process(event: dict) -> dict:
            """Tolerant reader: ignores unknown fields."""
            data = event["data"]
            return {
                "user_id":    data["user_id"],
                "email":      data["email"],
                "first_name": data["first_name"],   # alias field
                "last_name":  data["last_name"],    # alias field
                "plan":       data.get("plan"),
            }

        result = v1_consumer_process(sample_event_v2)
        assert result["first_name"] == "Jane"
        assert result["last_name"]  == "Doe"
        assert result["email"]      == "jane.doe@example.com"

    def test_v1_consumer_ignores_extra_v2_fields(self, sample_event_v2):
        """Unknown v2 fields (given_name, locale) are simply ignored."""
        data = sample_event_v2["data"]
        v1_known_fields = {"user_id", "email", "first_name", "last_name", "plan"}
        processed = {k: v for k, v in data.items() if k in v1_known_fields}
        assert "given_name" not in processed
        assert "locale"     not in processed
        assert processed["first_name"] == "Jane"


class TestEventTransformations:
    """Test upcast and downcast event transformations."""

    def test_upcast_v1_to_v2(self, sample_event_v1):
        v2_event = upcast_v1_to_v2(sample_event_v1)

        assert v2_event["event_version"] == "2.0"
        assert v2_event["data"]["given_name"]  == sample_event_v1["data"]["first_name"]
        assert v2_event["data"]["family_name"] == sample_event_v1["data"]["last_name"]
        # aliases preserved
        assert v2_event["data"]["first_name"] == sample_event_v1["data"]["first_name"]
        assert v2_event["data"]["last_name"]  == sample_event_v1["data"]["last_name"]
        # envelope unchanged
        assert v2_event["event_id"]   == sample_event_v1["event_id"]
        assert v2_event["event_type"] == "user.registered"

    def test_upcast_v1_to_v2_valid_against_v2_schema(self, sample_event_v1):
        """Upcasted event must pass v2 schema validation."""
        v2_event = upcast_v1_to_v2(sample_event_v1)
        schema   = _load_schema(V2_SCHEMA_PATH)
        jsonschema.validate(instance=v2_event, schema=schema)

    def test_downcast_v2_to_v1(self, sample_event_v2):
        v1_event = downcast_v2_to_v1(sample_event_v2)

        assert v1_event["event_version"] == "1.0"
        assert v1_event["data"]["first_name"] == sample_event_v2["data"]["given_name"]
        assert v1_event["data"]["last_name"]  == sample_event_v2["data"]["family_name"]
        # v2-only fields stripped
        assert "given_name"   not in v1_event["data"]
        assert "family_name"  not in v1_event["data"]
        assert "locale"       not in v1_event["data"]
        assert "display_name" not in v1_event["data"]

    def test_downcast_v2_to_v1_valid_against_v1_schema(self, sample_event_v2):
        """Downcasted event must pass v1 schema validation."""
        v1_event = downcast_v2_to_v1(sample_event_v2)
        schema   = _load_schema(V1_SCHEMA_PATH)
        jsonschema.validate(instance=v1_event, schema=schema)

    def test_upcast_downcast_roundtrip_preserves_core_fields(self, sample_event_v1):
        """Upcast then downcast must preserve all v1 core fields."""
        v2_event = upcast_v1_to_v2(sample_event_v1)
        v1_again = downcast_v2_to_v1(v2_event)

        orig_data = sample_event_v1["data"]
        trip_data = v1_again["data"]

        assert trip_data["email"]      == orig_data["email"]
        assert trip_data["first_name"] == orig_data["first_name"]
        assert trip_data["last_name"]  == orig_data["last_name"]
        assert trip_data["user_id"]    == orig_data["user_id"]


class TestCompatibilityRules:
    """Unit tests for the event compatibility rule engine."""

    def test_new_required_field_fails(self):
        """Adding a required field without a default must fail the compat check."""
        from compat.rules.event_compat_rules import check_backward_compatible

        old_schema = {
            "type": "object",
            "properties": {
                "data": {
                    "type": "object",
                    "required": ["user_id", "email"],
                    "properties": {
                        "user_id": {"type": "string"},
                        "email":   {"type": "string"},
                    },
                }
            },
        }
        new_schema = {
            "type": "object",
            "properties": {
                "data": {
                    "type": "object",
                    "required": ["user_id", "email", "phone"],  # phone added as required
                    "properties": {
                        "user_id": {"type": "string"},
                        "email":   {"type": "string"},
                        "phone":   {"type": "string"},          # no default
                    },
                }
            },
        }
        result = check_backward_compatible(old_schema, new_schema)
        assert result["status"] == "fail"
        assert "phone" in result["message"]

    def test_new_optional_field_passes(self):
        """Adding an optional (non-required) field must pass the compat check."""
        from compat.rules.event_compat_rules import check_backward_compatible

        old_schema = {
            "type": "object",
            "properties": {
                "data": {
                    "type": "object",
                    "required": ["user_id", "email"],
                    "properties": {
                        "user_id": {"type": "string"},
                        "email":   {"type": "string"},
                    },
                }
            },
        }
        new_schema = {
            "type": "object",
            "properties": {
                "data": {
                    "type": "object",
                    "required": ["user_id", "email"],  # required unchanged
                    "properties": {
                        "user_id": {"type": "string"},
                        "email":   {"type": "string"},
                        "phone":   {"type": "string"},  # optional new field
                    },
                }
            },
        }
        result = check_backward_compatible(old_schema, new_schema)
        assert result["status"] == "pass"

    def test_removing_property_fails(self):
        """Removing an existing property must fail backward compat."""
        from compat.rules.event_compat_rules import check_backward_compatible

        old_schema = {
            "type": "object",
            "properties": {
                "data": {
                    "type": "object",
                    "required": ["user_id", "email"],
                    "properties": {
                        "user_id": {"type": "string"},
                        "email":   {"type": "string"},
                        "plan":    {"type": "string"},
                    },
                }
            },
        }
        new_schema = {
            "type": "object",
            "properties": {
                "data": {
                    "type": "object",
                    "required": ["user_id", "email"],
                    "properties": {
                        "user_id": {"type": "string"},
                        "email":   {"type": "string"},
                        # plan removed
                    },
                }
            },
        }
        result = check_backward_compatible(old_schema, new_schema)
        assert result["status"] == "fail"
        assert "plan" in result["message"]
