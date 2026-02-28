"""
compat/rules/api_compat_rules.py
==================================
Rules for checking backward-compatibility between two OpenAPI 3.x specs.

All parsing is done with the standard ``yaml`` module; no external OpenAPI
library is required.

Each rule function accepts two parsed spec dicts (old, new) and returns::

    {
        "rule":    "<rule name>",
        "status":  "pass" | "warn" | "fail",
        "message": "<human-readable description>",
    }

``run_all_checks`` loads two YAML files and runs every rule.
"""

from __future__ import annotations

import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

RuleResult = Dict[str, str]

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_yaml(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _resolve_ref(spec: Dict[str, Any], ref: str) -> Optional[Dict[str, Any]]:
    """Resolve a simple local $ref like '#/components/schemas/Foo'."""
    if not ref.startswith("#/"):
        return None
    parts = ref.lstrip("#/").split("/")
    node: Any = spec
    for part in parts:
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node if isinstance(node, dict) else None


def _deref(spec: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
    """Return the schema with any top-level $ref resolved (single level)."""
    if "$ref" in schema:
        resolved = _resolve_ref(spec, schema["$ref"])
        return resolved if resolved is not None else schema
    return schema


def _collect_response_schemas(
    spec: Dict[str, Any]
) -> Dict[str, Dict[str, Any]]:
    """
    Collect all response schemas keyed by '<method>:<path>.<statusCode>'.

    Using path+method as the key (instead of operationId) ensures that
    v1 and v2 specs with different operationIds are still matched correctly
    when comparing compatibility across versions.
    Only 2xx responses are considered.
    """
    schemas: Dict[str, Dict[str, Any]] = {}
    paths = spec.get("paths", {})
    for _path, path_item in paths.items():
        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete", "head"}:
                continue
            if not isinstance(operation, dict):
                continue
            responses = operation.get("responses", {})
            for status_code, response in responses.items():
                if not str(status_code).startswith("2"):
                    continue
                content = response.get("content", {})
                json_content = content.get("application/json", {})
                schema = json_content.get("schema")
                if schema is None:
                    continue
                schema = _deref(spec, schema)
                key = f"{method}:{_path}.{status_code}"
                schemas[key] = schema
    return schemas


def _collect_request_schemas(
    spec: Dict[str, Any]
) -> Dict[str, Dict[str, Any]]:
    """Collect request body schemas keyed by '<method>:<path>.request'."""
    schemas: Dict[str, Dict[str, Any]] = {}
    paths = spec.get("paths", {})
    for _path, path_item in paths.items():
        for method, operation in path_item.items():
            if method not in {"post", "put", "patch"}:
                continue
            if not isinstance(operation, dict):
                continue
            request_body = operation.get("requestBody", {})
            content = request_body.get("content", {})
            json_content = content.get("application/json", {})
            schema = json_content.get("schema")
            if schema is None:
                continue
            schema = _deref(spec, schema)
            schemas[f"{method}:{_path}.request"] = schema
    return schemas


def _get_properties(
    spec: Dict[str, Any], schema: Dict[str, Any]
) -> Dict[str, Dict[str, Any]]:
    """Return the properties dict of a schema, resolving nested $refs."""
    props = schema.get("properties", {})
    result: Dict[str, Dict[str, Any]] = {}
    for name, prop_schema in props.items():
        result[name] = _deref(spec, prop_schema)
    return result


def _get_required(schema: Dict[str, Any]) -> Set[str]:
    return set(schema.get("required", []))


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def check_no_required_field_added(
    old_spec: Dict[str, Any], new_spec: Dict[str, Any]
) -> RuleResult:
    """
    Fail if the new spec adds a required field to a request body schema
    without providing a default value.

    Adding a required field without a default breaks existing clients that
    do not send that field.
    """
    old_requests = _collect_request_schemas(old_spec)
    new_requests = _collect_request_schemas(new_spec)

    violations: List[str] = []

    for key, new_schema in new_requests.items():
        old_schema = old_requests.get(key, {})
        old_required = _get_required(old_schema)
        new_required = _get_required(new_schema)
        added = new_required - old_required

        new_props = _get_properties(new_spec, new_schema)
        for field in added:
            prop = new_props.get(field, {})
            if "default" not in prop:
                violations.append(f"  - '{field}' in '{key}'")

    if violations:
        return {
            "rule": "no_required_field_added",
            "status": "fail",
            "message": (
                "New required field(s) added to request body without a default "
                "value – breaks existing clients:\n" + "\n".join(violations)
            ),
        }
    return {
        "rule": "no_required_field_added",
        "status": "pass",
        "message": "No new required request fields added without defaults.",
    }


def check_no_field_removed(
    old_spec: Dict[str, Any], new_spec: Dict[str, Any]
) -> RuleResult:
    """
    Fail if a property is removed from any response schema.

    Removing a field from a response breaks consumers that depend on it.
    """
    old_responses = _collect_response_schemas(old_spec)
    new_responses = _collect_response_schemas(new_spec)

    violations: List[str] = []

    for key, old_schema in old_responses.items():
        new_schema = new_responses.get(key)
        if new_schema is None:
            violations.append(f"  - response schema '{key}' removed entirely")
            continue

        old_props = set(_get_properties(old_spec, old_schema).keys())
        new_props = set(_get_properties(new_spec, new_schema).keys())
        removed = old_props - new_props
        for field in removed:
            violations.append(f"  - '{field}' removed from '{key}'")

    if violations:
        return {
            "rule": "no_field_removed",
            "status": "fail",
            "message": (
                "Field(s) removed from response schema – breaks existing "
                "consumers:\n" + "\n".join(violations)
            ),
        }
    return {
        "rule": "no_field_removed",
        "status": "pass",
        "message": "No response fields removed.",
    }


def check_no_type_changed(
    old_spec: Dict[str, Any], new_spec: Dict[str, Any]
) -> RuleResult:
    """
    Fail if the type of any response field changes between versions.

    A type change is a breaking change for consumers that deserialise into
    typed structures.
    """
    old_responses = _collect_response_schemas(old_spec)
    new_responses = _collect_response_schemas(new_spec)

    violations: List[str] = []

    for key, old_schema in old_responses.items():
        new_schema = new_responses.get(key)
        if new_schema is None:
            continue

        old_props = _get_properties(old_spec, old_schema)
        new_props = _get_properties(new_spec, new_schema)

        for field, old_prop in old_props.items():
            new_prop = new_props.get(field)
            if new_prop is None:
                continue
            old_type = old_prop.get("type")
            new_type = new_prop.get("type")
            if old_type and new_type and old_type != new_type:
                violations.append(
                    f"  - '{field}' in '{key}': type changed from '{old_type}' to '{new_type}'"
                )

    if violations:
        return {
            "rule": "no_type_changed",
            "status": "fail",
            "message": (
                "Field type change(s) detected in response schema:\n"
                + "\n".join(violations)
            ),
        }
    return {
        "rule": "no_type_changed",
        "status": "pass",
        "message": "No field type changes detected.",
    }


def check_deprecation_notice(
    old_spec: Dict[str, Any], new_spec: Dict[str, Any]
) -> RuleResult:
    """
    Warn if a field that was not marked x-deprecated in the old spec is
    absent from the new spec.

    Removing a field without first deprecating it skips the communication
    window that consumers need to migrate.
    """
    old_responses = _collect_response_schemas(old_spec)
    new_responses = _collect_response_schemas(new_spec)

    violations: List[str] = []

    for key, old_schema in old_responses.items():
        new_schema = new_responses.get(key)
        if new_schema is None:
            continue

        old_props = _get_properties(old_spec, old_schema)
        new_prop_names = set(_get_properties(new_spec, new_schema).keys())

        for field, old_prop in old_props.items():
            if field not in new_prop_names:
                was_deprecated = old_prop.get("x-deprecated", False)
                if not was_deprecated:
                    violations.append(
                        f"  - '{field}' in '{key}' removed without prior x-deprecated marker"
                    )

    if violations:
        return {
            "rule": "deprecation_notice",
            "status": "warn",
            "message": (
                "Field(s) removed without a prior deprecation notice.  "
                "Consumers may not have had time to migrate:\n"
                + "\n".join(violations)
            ),
        }
    return {
        "rule": "deprecation_notice",
        "status": "pass",
        "message": "All removed fields had prior deprecation notices.",
    }


# ---------------------------------------------------------------------------
# Aggregate runner
# ---------------------------------------------------------------------------

_ALL_RULES = [
    check_no_required_field_added,
    check_no_field_removed,
    check_no_type_changed,
    check_deprecation_notice,
]


def run_all_checks(old_spec_path: str, new_spec_path: str) -> List[RuleResult]:
    """
    Load two OpenAPI YAML files and run every compatibility rule.

    Returns a list of :class:`RuleResult` dicts, one per rule.
    """
    old_spec = _load_yaml(old_spec_path)
    new_spec = _load_yaml(new_spec_path)
    return [rule(old_spec, new_spec) for rule in _ALL_RULES]
