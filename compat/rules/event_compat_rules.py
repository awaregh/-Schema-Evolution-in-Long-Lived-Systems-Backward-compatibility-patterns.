"""
compat/rules/event_compat_rules.py
=====================================
Rules for checking backward-compatibility between two JSON Schema event
definitions.

All parsing is done with the standard ``json`` module; no external schema
library is required for the rule checks themselves.

Each rule function accepts two parsed schema dicts (old, new) and returns::

    {
        "rule":    "<rule name>",
        "status":  "pass" | "warn" | "fail",
        "message": "<human-readable description>",
    }

``run_all_checks`` loads two JSON files and runs every rule.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

RuleResult = Dict[str, str]

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _get_data_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Return the nested 'data' property schema, or an empty dict."""
    props = schema.get("properties", {})
    data_schema = props.get("data", {})
    return data_schema if isinstance(data_schema, dict) else {}


def _get_required(schema: Dict[str, Any]) -> Set[str]:
    return set(schema.get("required", []))


def _get_properties(schema: Dict[str, Any]) -> Dict[str, Any]:
    return schema.get("properties", {})


def _extract_version(schema: Dict[str, Any]) -> Optional[str]:
    """
    Extract the event_version const value from the top-level schema.
    Returns None if not found.
    """
    props = schema.get("properties", {})
    ev = props.get("event_version", {})
    return ev.get("const") or ev.get("enum", [None])[0]


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def check_no_required_removed(
    old_schema: Dict[str, Any], new_schema: Dict[str, Any]
) -> RuleResult:
    """
    Fail if a field that was required in the old schema's ``data`` object
    is no longer present in the new schema's required list.

    Removing a required field changes the contract that producers fulfil;
    consumers that rely on the field being present will break.

    Note: this is the *inverse* of the API rule.  For events, producers
    write and consumers read – removing a required field from the schema
    means producers may stop including it, breaking consumers.
    """
    old_data = _get_data_schema(old_schema)
    new_data = _get_data_schema(new_schema)

    old_required = _get_required(old_data)
    new_required = _get_required(new_data)

    removed = old_required - new_required

    # Also check top-level required fields
    old_top_required = _get_required(old_schema)
    new_top_required = _get_required(new_schema)
    top_removed = old_top_required - new_top_required

    all_removed = removed | top_removed

    if all_removed:
        fields = ", ".join(sorted(all_removed))
        return {
            "rule": "no_required_removed",
            "status": "fail",
            "message": (
                f"Required field(s) removed from event schema: {fields}.  "
                "Producers may stop including these fields, breaking consumers "
                "that depend on them."
            ),
        }
    return {
        "rule": "no_required_removed",
        "status": "pass",
        "message": "No required fields removed.",
    }


def check_no_type_changed(
    old_schema: Dict[str, Any], new_schema: Dict[str, Any]
) -> RuleResult:
    """
    Fail if the JSON type of any property in the ``data`` object changes.

    A type change forces all consumers to update their deserialisation logic
    and is not backward-compatible.
    """
    old_data  = _get_data_schema(old_schema)
    new_data  = _get_data_schema(new_schema)
    old_props = _get_properties(old_data)
    new_props = _get_properties(new_data)

    violations: List[str] = []

    for field, old_prop in old_props.items():
        new_prop = new_props.get(field)
        if new_prop is None:
            continue
        old_type = old_prop.get("type")
        new_type = new_prop.get("type")
        if old_type and new_type and old_type != new_type:
            violations.append(
                f"  - '{field}': type changed from '{old_type}' to '{new_type}'"
            )
        # Check const value changes (e.g. event_version const)
        old_const = old_prop.get("const")
        new_const = new_prop.get("const")
        # const changes on non-versioning fields are breaking
        if old_const is not None and new_const is not None and old_const != new_const:
            if field not in ("event_version",):
                violations.append(
                    f"  - '{field}': const changed from '{old_const}' to '{new_const}'"
                )

    # Also check top-level properties
    old_top = _get_properties(old_schema)
    new_top = _get_properties(new_schema)
    for field, old_prop in old_top.items():
        if field == "data":
            continue
        new_prop = new_top.get(field)
        if new_prop is None:
            continue
        old_type = old_prop.get("type")
        new_type = new_prop.get("type")
        if old_type and new_type and old_type != new_type:
            violations.append(
                f"  - (top-level) '{field}': type changed from '{old_type}' to '{new_type}'"
            )

    if violations:
        return {
            "rule": "no_type_changed",
            "status": "fail",
            "message": (
                "Property type change(s) detected:\n" + "\n".join(violations)
            ),
        }
    return {
        "rule": "no_type_changed",
        "status": "pass",
        "message": "No property type changes detected.",
    }


def check_version_bumped(
    old_schema: Dict[str, Any], new_schema: Dict[str, Any]
) -> RuleResult:
    """
    Warn if the event_version const has not changed between schemas.

    When the data shape changes (new fields, deprecated fields, etc.) the
    version string should be incremented so consumers can distinguish events.
    """
    old_version = _extract_version(old_schema)
    new_version = _extract_version(new_schema)

    old_data  = _get_data_schema(old_schema)
    new_data  = _get_data_schema(new_schema)
    old_props = set(_get_properties(old_data).keys())
    new_props = set(_get_properties(new_data).keys())
    schema_changed = old_props != new_props

    if schema_changed and old_version == new_version:
        return {
            "rule": "version_bumped",
            "status": "warn",
            "message": (
                f"The data schema has changed (fields added/removed) but "
                f"event_version is still '{old_version}'.  Consider bumping "
                "the version so consumers can identify the schema variant."
            ),
        }
    return {
        "rule": "version_bumped",
        "status": "pass",
        "message": (
            f"Version check passed "
            f"(old={old_version!r}, new={new_version!r}, "
            f"schema_changed={schema_changed})."
        ),
    }


def check_backward_compatible(
    old_schema: Dict[str, Any], new_schema: Dict[str, Any]
) -> RuleResult:
    """
    Comprehensive check: a new schema is backward-compatible if every
    message valid under the *old* schema is also valid under the *new* schema.

    Practical rules for JSON Schema event compatibility:
      1. New fields added to ``data`` must be optional (not in ``required``).
      2. No existing ``data`` properties may be removed.
      3. The ``additionalProperties`` setting must not become ``false`` if it
         was not already.

    Returns "pass" if all sub-checks succeed, "fail" otherwise.
    """
    issues: List[str] = []

    old_data  = _get_data_schema(old_schema)
    new_data  = _get_data_schema(new_schema)
    old_props = _get_properties(old_data)
    new_props = _get_properties(new_data)
    new_required = _get_required(new_data)

    # 1. New required fields without defaults break old producers
    for field in new_required - _get_required(old_data):
        prop = new_props.get(field, {})
        if "default" not in prop:
            issues.append(
                f"New required field '{field}' has no default – old producers "
                "won't include it."
            )

    # 2. Removed properties break old consumers
    for field in set(old_props.keys()) - set(new_props.keys()):
        issues.append(
            f"Property '{field}' present in old schema but removed in new – "
            "consumers relying on it will break."
        )

    # 3. additionalProperties tightening
    old_add = old_data.get("additionalProperties", True)
    new_add = new_data.get("additionalProperties", True)
    if old_add is not False and new_add is False:
        issues.append(
            "additionalProperties changed from open to false – old events with "
            "extra fields will now fail validation."
        )

    if issues:
        detail = "\n".join(f"  - {i}" for i in issues)
        return {
            "rule": "backward_compatible",
            "status": "fail",
            "message": f"Backward-compatibility violations detected:\n{detail}",
        }
    return {
        "rule": "backward_compatible",
        "status": "pass",
        "message": "New schema is backward-compatible with the old schema.",
    }


# ---------------------------------------------------------------------------
# Aggregate runner
# ---------------------------------------------------------------------------

_ALL_RULES = [
    check_no_required_removed,
    check_no_type_changed,
    check_version_bumped,
    check_backward_compatible,
]


def run_all_checks(old_schema_path: str, new_schema_path: str) -> List[RuleResult]:
    """
    Load two JSON Schema files and run every compatibility rule.

    Returns a list of :class:`RuleResult` dicts, one per rule.
    """
    old_schema = _load_json(old_schema_path)
    new_schema = _load_json(new_schema_path)
    return [rule(old_schema, new_schema) for rule in _ALL_RULES]
