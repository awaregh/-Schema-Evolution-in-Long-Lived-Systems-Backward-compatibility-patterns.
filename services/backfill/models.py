"""
SQLAlchemy ORM model for the backfill_jobs tracking table.

Each row represents one execution of a named backfill job.  The worker
creates a row in ``pending`` state before starting, transitions it to
``running``, and finally marks it ``completed`` or ``failed``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class BackfillJob(Base):
    """
    Tracks progress and outcome of each backfill job execution.

    Columns
    -------
    id              Serial surrogate PK.
    job_name        Logical name of the backfill job (e.g. ``backfill_given_name``).
    status          Lifecycle state: pending → running → completed | failed.
    rows_processed  Running count of rows successfully updated.
    rows_total      Total rows that need backfilling (set at job start, nullable
                    until the count query completes).
    error_message   Last exception message when status=failed; NULL otherwise.
    started_at      Timestamp when the worker picked up the job.
    completed_at    Timestamp when the job reached a terminal state (nullable).
    created_at      Row-insertion timestamp; used to order job history.
    """

    __tablename__ = "backfill_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    job_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # pending | running | completed | failed
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True
    )

    rows_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Populated after counting outstanding rows at job start
    rows_total: Mapped[int | None] = mapped_column(Integer, nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=_now,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<BackfillJob id={self.id} job_name={self.job_name!r} "
            f"status={self.status!r} rows_processed={self.rows_processed}>"
        )
