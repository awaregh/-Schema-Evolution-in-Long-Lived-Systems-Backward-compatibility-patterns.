"""
tests/conftest.py
==================
Shared pytest fixtures for all Schema Evolution tests.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# User fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_user_v1() -> dict:
    """A user record in v1 format (first_name / last_name)."""
    return {
        "id": str(uuid.uuid4()),
        "first_name": "Jane",
        "last_name": "Doe",
        "email": "jane.doe@example.com",
        "phone": "+14155552671",
        "status": "active",
        "plan": "pro",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }


@pytest.fixture
def sample_user_v2() -> dict:
    """A user record in v2 format (given_name / family_name + deprecated aliases)."""
    return {
        "id": str(uuid.uuid4()),
        "given_name": "Jane",
        "family_name": "Doe",
        # backward-compat aliases
        "first_name": "Jane",
        "last_name": "Doe",
        "email": "jane.doe@example.com",
        "phone": "+14155552671",
        "status": "active",
        "plan": "pro",
        "display_name": "Jane Doe",
        "locale": "en-US",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }


# ---------------------------------------------------------------------------
# Event fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_event_v1() -> dict:
    """A user.registered event in v1 format."""
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "user.registered",
        "event_version": "1.0",
        "timestamp": _now_iso(),
        "correlation_id": str(uuid.uuid4()),
        "data": {
            "user_id": str(uuid.uuid4()),
            "email": "jane.doe@example.com",
            "first_name": "Jane",
            "last_name": "Doe",
            "plan": "free",
        },
    }


@pytest.fixture
def sample_event_v2() -> dict:
    """A user.registered event in v2 format (canonical + compat aliases)."""
    user_id = str(uuid.uuid4())
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "user.registered",
        "event_version": "2.0",
        "timestamp": _now_iso(),
        "correlation_id": str(uuid.uuid4()),
        "data": {
            "user_id": user_id,
            "email": "jane.doe@example.com",
            # canonical v2 fields
            "given_name": "Jane",
            "family_name": "Doe",
            # deprecated aliases for v1 backward compat
            "first_name": "Jane",
            "last_name": "Doe",
            "plan": "free",
            "locale": "en-US",
        },
    }


# ---------------------------------------------------------------------------
# Subscription event fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_subscription_event_v1() -> dict:
    """A subscription.created event in v1 format (amount_cents only)."""
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "subscription.created",
        "event_version": "1.0",
        "timestamp": _now_iso(),
        "data": {
            "subscription_id": str(uuid.uuid4()),
            "user_id": str(uuid.uuid4()),
            "plan": "pro",
            "amount_cents": 999,
            "currency": "USD",
            "billing_period": "monthly",
        },
    }


@pytest.fixture
def sample_subscription_event_v2() -> dict:
    """A subscription.created event in v2 format (amount + amount_cents)."""
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "subscription.created",
        "event_version": "2.0",
        "timestamp": _now_iso(),
        "data": {
            "subscription_id": str(uuid.uuid4()),
            "user_id": str(uuid.uuid4()),
            "plan": "pro",
            "amount": "9.99",
            "amount_cents": 999,
            "currency": "USD",
            "billing_period": "monthly",
        },
    }
