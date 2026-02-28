"""
API v1 – Analytics router.

Endpoints
---------
POST /api/v1/events          – ingest a domain event into the EventLog
GET  /api/v1/events          – list events with optional filtering
GET  /api/v1/aggregates      – get pre-computed user-event aggregates
GET  /api/v1/stats           – system-level statistics
GET  /health                 – liveness probe
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.analytics import EventLog, UserEventAggregate
from app.schemas.analytics import (
    EventIngest,
    EventLogResponse,
    StatsResponse,
    UserEventAggregateResponse,
)

router = APIRouter(tags=["analytics-v1"])


# ── health ────────────────────────────────────────────────────────────────────


@router.get("/health", tags=["ops"])
def health() -> dict:
    return {"status": "ok", "version": "v1", "consumer_version": settings.CONSUMER_VERSION}


# ── event ingestion ───────────────────────────────────────────────────────────


@router.post(
    "/api/v1/events",
    response_model=EventLogResponse,
    status_code=status.HTTP_201_CREATED,
)
def ingest_event(payload: EventIngest, db: Session = Depends(get_db)) -> EventLog:
    """Store an inbound domain event in the EventLog for async processing."""
    event = EventLog(
        event_type=payload.event_type,
        event_version=payload.event_version,
        payload=payload.payload,
        source_service=payload.source_service,
        processed=False,
        schema_version=1,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


# ── event listing ─────────────────────────────────────────────────────────────


@router.get("/api/v1/events", response_model=List[EventLogResponse])
def list_events(
    event_type: Optional[str] = None,
    source_service: Optional[str] = None,
    processed: Optional[bool] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> List[EventLog]:
    stmt = select(EventLog).order_by(EventLog.created_at.desc())
    if event_type is not None:
        stmt = stmt.where(EventLog.event_type == event_type)
    if source_service is not None:
        stmt = stmt.where(EventLog.source_service == source_service)
    if processed is not None:
        stmt = stmt.where(EventLog.processed == processed)
    stmt = stmt.offset(skip).limit(limit)
    return list(db.execute(stmt).scalars().all())


# ── aggregates ────────────────────────────────────────────────────────────────


@router.get(
    "/api/v1/aggregates",
    response_model=List[UserEventAggregateResponse],
)
def list_aggregates(
    user_id: Optional[uuid.UUID] = None,
    event_type: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> List[UserEventAggregate]:
    stmt = (
        select(UserEventAggregate)
        .order_by(UserEventAggregate.date.desc())
        .offset(skip)
        .limit(limit)
    )
    if user_id is not None:
        stmt = stmt.where(UserEventAggregate.user_id == user_id)
    if event_type is not None:
        stmt = stmt.where(UserEventAggregate.event_type == event_type)
    return list(db.execute(stmt).scalars().all())


# ── stats ─────────────────────────────────────────────────────────────────────


@router.get("/api/v1/stats", response_model=StatsResponse)
def get_stats(db: Session = Depends(get_db)) -> StatsResponse:
    """Return aggregate system metrics useful for schema-evolution research."""
    total = db.execute(
        select(func.count()).select_from(EventLog)
    ).scalar_one()
    processed = db.execute(
        select(func.count()).select_from(EventLog).where(EventLog.processed.is_(True))
    ).scalar_one()
    errors = db.execute(
        select(func.count())
        .select_from(EventLog)
        .where(EventLog.processing_error.isnot(None))
    ).scalar_one()
    total_aggs = db.execute(
        select(func.count()).select_from(UserEventAggregate)
    ).scalar_one()

    return StatsResponse(
        total_events=total,
        processed_events=processed,
        unprocessed_events=total - processed,
        error_events=errors,
        total_aggregates=total_aggs,
        consumer_version=settings.CONSUMER_VERSION,
    )
