"""
tests/contract/test_api_compat.py
====================================
Tests for OpenAPI spec backward-compatibility rule engine.

Covers:
  - Additive changes (new optional fields) pass
  - Removing response fields fails
  - Adding required request fields fails
  - Removing fields without prior deprecation warns
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

# ---------------------------------------------------------------------------
# Import rule functions directly for unit tests
# ---------------------------------------------------------------------------

import sys
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from compat.rules.api_compat_rules import (  # noqa: E402
    check_no_required_field_added,
    check_no_field_removed,
    check_no_type_changed,
    check_deprecation_notice,
    run_all_checks,
)

# ---------------------------------------------------------------------------
# Spec factory helpers
# ---------------------------------------------------------------------------

def _make_spec(
    op_id: str = "getUser",
    response_properties: Dict[str, Any] | None = None,
    request_properties: Dict[str, Any] | None = None,
    request_required: list | None = None,
    response_required: list | None = None,
) -> Dict[str, Any]:
    """Build a minimal OpenAPI 3.x spec dict for testing."""
    response_properties = response_properties or {
        "id":    {"type": "string"},
        "email": {"type": "string"},
        "name":  {"type": "string"},
    }
    request_properties = request_properties or {
        "email": {"type": "string"},
        "name":  {"type": "string"},
    }
    request_required = request_required or ["email"]

    spec: Dict[str, Any] = {
        "openapi": "3.0.3",
        "info": {"title": "Test", "version": "1.0"},
        "paths": {
            "/users": {
                "post": {
                    "operationId": op_id,
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": request_required,
                                    "properties": request_properties,
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": response_required or list(response_properties.keys()),
                                        "properties": response_properties,
                                    }
                                }
                            },
                        }
                    },
                }
            }
        },
    }
    return spec


def _dump_yaml(spec: dict) -> str:
    """Serialise a spec dict to a YAML string."""
    return yaml.dump(spec, default_flow_style=False)


def _write_temp_yaml(spec: dict) -> str:
    """Write spec to a temporary file and return the path."""
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w") as fh:
        fh.write(_dump_yaml(spec))
    return path


# ---------------------------------------------------------------------------
# Tests: additive changes
# ---------------------------------------------------------------------------

class TestAdditiveChanges:

    def test_v1_to_v2_additive_change_passes(self):
        """Adding new optional response fields must pass all checks."""
        old_spec = _make_spec(
            response_properties={"id": {"type": "string"}, "email": {"type": "string"}},
        )
        new_spec = _make_spec(
            response_properties={
                "id":    {"type": "string"},
                "email": {"type": "string"},
                "phone": {"type": "string"},  # new optional field
            },
        )
        result_removed    = check_no_field_removed(old_spec, new_spec)
        result_type       = check_no_type_changed(old_spec, new_spec)
        result_required   = check_no_required_field_added(old_spec, new_spec)

        assert result_removed["status"]  == "pass"
        assert result_type["status"]     == "pass"
        assert result_required["status"] == "pass"

    def test_adding_new_optional_request_field_passes(self):
        """Adding an optional (non-required) request field must pass."""
        old_spec = _make_spec(
            request_properties={"email": {"type": "string"}},
            request_required=["email"],
        )
        new_spec = _make_spec(
            request_properties={"email": {"type": "string"}, "phone": {"type": "string"}},
            request_required=["email"],  # phone is NOT required
        )
        result = check_no_required_field_added(old_spec, new_spec)
        assert result["status"] == "pass"


# ---------------------------------------------------------------------------
# Tests: removing response fields
# ---------------------------------------------------------------------------

class TestRemovingFields:

    def test_removing_required_field_fails(self):
        """Removing a required response field must fail."""
        old_spec = _make_spec(
            response_properties={"id": {"type": "string"}, "email": {"type": "string"}},
        )
        new_spec = _make_spec(
            response_properties={"id": {"type": "string"}},  # email removed
        )
        result = check_no_field_removed(old_spec, new_spec)
        assert result["status"] == "fail"
        assert "email" in result["message"]

    def test_removing_optional_response_field_fails(self):
        """Even optional response fields may not be removed (consumers may read them)."""
        old_spec = _make_spec(
            response_properties={
                "id":    {"type": "string"},
                "email": {"type": "string"},
                "bio":   {"type": "string"},
            },
        )
        new_spec = _make_spec(
            response_properties={
                "id":    {"type": "string"},
                "email": {"type": "string"},
                # bio removed
            },
        )
        result = check_no_field_removed(old_spec, new_spec)
        assert result["status"] == "fail"
        assert "bio" in result["message"]


# ---------------------------------------------------------------------------
# Tests: adding required request fields
# ---------------------------------------------------------------------------

class TestAddingRequiredFields:

    def test_adding_required_field_fails(self):
        """Adding a required request field without a default must fail."""
        old_spec = _make_spec(
            request_properties={"email": {"type": "string"}},
            request_required=["email"],
        )
        new_spec = _make_spec(
            request_properties={
                "email": {"type": "string"},
                "phone": {"type": "string"},   # no default
            },
            request_required=["email", "phone"],  # phone is now required
        )
        result = check_no_required_field_added(old_spec, new_spec)
        assert result["status"] == "fail"
        assert "phone" in result["message"]

    def test_adding_required_field_with_default_passes(self):
        """Adding a required field WITH a default is backward-compatible."""
        old_spec = _make_spec(
            request_properties={"email": {"type": "string"}},
            request_required=["email"],
        )
        new_spec = _make_spec(
            request_properties={
                "email":  {"type": "string"},
                "status": {"type": "string", "default": "active"},  # has default
            },
            request_required=["email", "status"],
        )
        result = check_no_required_field_added(old_spec, new_spec)
        assert result["status"] == "pass"


# ---------------------------------------------------------------------------
# Tests: deprecation notice
# ---------------------------------------------------------------------------

class TestDeprecationNotice:

    def test_deprecation_notice_required_when_field_removed(self):
        """Removing a field that was not previously deprecated must warn."""
        old_spec = _make_spec(
            response_properties={
                "id":    {"type": "string"},
                "email": {"type": "string"},
                "bio":   {"type": "string"},   # no x-deprecated
            },
        )
        new_spec = _make_spec(
            response_properties={
                "id":    {"type": "string"},
                "email": {"type": "string"},
                # bio removed without prior deprecation
            },
        )
        result = check_deprecation_notice(old_spec, new_spec)
        assert result["status"] == "warn"
        assert "bio" in result["message"]

    def test_deprecated_field_removal_passes_notice_check(self):
        """Removing a field that was marked x-deprecated must pass the notice check."""
        old_spec = _make_spec(
            response_properties={
                "id":    {"type": "string"},
                "email": {"type": "string"},
                "bio":   {"type": "string", "x-deprecated": True},  # deprecated
            },
        )
        new_spec = _make_spec(
            response_properties={
                "id":    {"type": "string"},
                "email": {"type": "string"},
                # bio removed – was deprecated, so this is fine
            },
        )
        result = check_deprecation_notice(old_spec, new_spec)
        assert result["status"] == "pass"


# ---------------------------------------------------------------------------
# Tests: type changes
# ---------------------------------------------------------------------------

class TestTypeChanges:

    def test_type_change_fails(self):
        """Changing a field type is a breaking change."""
        old_spec = _make_spec(
            response_properties={"id": {"type": "string"}, "count": {"type": "integer"}},
        )
        new_spec = _make_spec(
            response_properties={"id": {"type": "string"}, "count": {"type": "string"}},  # was int
        )
        result = check_no_type_changed(old_spec, new_spec)
        assert result["status"] == "fail"
        assert "count" in result["message"]

    def test_same_type_passes(self):
        """Keeping field types unchanged must pass."""
        spec = _make_spec(
            response_properties={"id": {"type": "string"}, "email": {"type": "string"}},
        )
        result = check_no_type_changed(spec, spec)
        assert result["status"] == "pass"


# ---------------------------------------------------------------------------
# Integration test: run_all_checks with real files
# ---------------------------------------------------------------------------

class TestRunAllChecksIntegration:

    def test_v1_to_v2_full_check_passes(self):
        """
        The real users_v1 → users_v2 specs must pass all compat checks.
        (The v2 spec uses deprecated aliases, not removals.)
        """
        old_path = str(REPO_ROOT / "contracts" / "api" / "users_v1.yaml")
        new_path = str(REPO_ROOT / "contracts" / "api" / "users_v2.yaml")

        if not (Path(old_path).exists() and Path(new_path).exists()):
            pytest.skip("Contract spec files not found")

        results = run_all_checks(old_path, new_path)
        failures = [r for r in results if r["status"] == "fail"]
        assert failures == [], f"Unexpected failures: {failures}"
