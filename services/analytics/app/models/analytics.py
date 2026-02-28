"""
SQLAlchemy ORM models for the Analytics service.

EventLog captures every inbound domain event for replay and analysis.
UserEventAggregate maintains pre-computed per-user counters for fast reads.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class EventLog(Base):
    """
    Immutable append-only log of domain events.

    ``event_version`` tracks the payload schema version so that consumers
    can apply upcasting/downcasting when reading events.
    ``schema_version`` tracks which version of this table schema wrote the row.
    """

    __tablename__ = "event_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    event_version: Mapped[str] = mapped_column(
        String(10), nullable=False, default="1.0"
    )
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_service: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    processed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=_now,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=_now,
        onupdate=_now,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<EventLog id={self.id} event_type={self.event_type!r} "
            f"version={self.event_version} processed={self.processed}>"
        )


class UserEventAggregate(Base):
    """
    Pre-computed per-user event count aggregates, partitioned by date.

    The unique constraint on (user_id, event_type, date) enables upsert
    semantics so the processor can safely re-run without double-counting.
    """

    __tablename__ = "user_event_aggregates"
    __table_args__ = (
        UniqueConstraint("user_id", "event_type", "date", name="uq_user_event_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_seen: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=_now,
        onupdate=_now,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<UserEventAggregate user_id={self.user_id} "
            f"event_type={self.event_type!r} date={self.date} count={self.count}>"
        )
