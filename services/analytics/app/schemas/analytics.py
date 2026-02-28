"""
Pydantic schemas for the Analytics service.

EventPayloadV1 uses ``first_name`` / ``last_name`` field names.
EventPayloadV2 uses ``given_name`` / ``family_name`` – mirroring the Users
service field-rename migration so analytics can demonstrate consumer-side
tolerant reader / upcasting strategies.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Event payload schemas ─────────────────────────────────────────────────────


class EventPayloadV1(BaseModel):
    """Payload produced by v1 event sources – uses original field names."""

    user_id: Optional[uuid.UUID] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    extra: Optional[Any] = None

    model_config = {"extra": "allow"}


class EventPayloadV2(BaseModel):
    """
    Payload produced by v2 event sources – uses renamed fields.

    Tolerant reader: also accepts the old v1 field names so a mixed-version
    environment does not break consumers.
    """

    user_id: Optional[uuid.UUID] = None
    given_name: Optional[str] = None
    family_name: Optional[str] = None
    # Backward-compatibility aliases retained during transition
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    extra: Optional[Any] = None

    model_config = {"extra": "allow"}


# ── EventLog schemas ──────────────────────────────────────────────────────────


class EventIngest(BaseModel):
    """Request body for POST /api/v1/events."""

    event_type: str = Field(..., max_length=100)
    event_version: str = Field("1.0", max_length=10)
    payload: Optional[Any] = None
    source_service: str = Field(..., max_length=50)


class EventLogResponse(BaseModel):
    id: uuid.UUID
    event_type: str
    event_version: str
    payload: Optional[Any]
    source_service: str
    processed: bool
    processing_error: Optional[str]
    schema_version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── UserEventAggregate schemas ────────────────────────────────────────────────


class UserEventAggregateResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    event_type: str
    count: int
    last_seen: Optional[datetime]
    date: date
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Stats schema ──────────────────────────────────────────────────────────────


class StatsResponse(BaseModel):
    total_events: int
    processed_events: int
    unprocessed_events: int
    error_events: int
    total_aggregates: int
    consumer_version: str
