"""
Analytics event processor.

Reads unprocessed EventLog rows and updates UserEventAggregate counters.

Consumer versioning
-------------------
The CONSUMER_VERSION environment variable controls which field names the
processor reads from the event payload, demonstrating the tolerant-reader
and upcasting/downcasting patterns:

  v1 consumer : reads ``first_name`` (original field name).
  v2 consumer : reads ``given_name``, falls back to ``first_name`` when
                ``given_name`` is absent (tolerant reader).

upcast()   – converts a v1 event payload to v2 format before processing.
downcast() – converts a v2 event payload to v1 format for legacy consumers.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.analytics import EventLog, UserEventAggregate

logger = logging.getLogger(__name__)


# ── Schema transformation helpers ─────────────────────────────────────────────


def upcast(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Upcast a v1 event payload to v2 format.

    Renames ``first_name`` → ``given_name`` and ``last_name`` → ``family_name``
    while keeping the originals for backward compatibility.
    """
    result = dict(payload)
    if "first_name" in result and "given_name" not in result:
        result["given_name"] = result["first_name"]
    if "last_name" in result and "family_name" not in result:
        result["family_name"] = result["last_name"]
    return result


def downcast(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Downcast a v2 event payload to v1 format.

    Maps ``given_name`` → ``first_name`` and ``family_name`` → ``last_name``
    so legacy v1 consumers can process v2 events without change.
    """
    result = dict(payload)
    if "given_name" in result and "first_name" not in result:
        result["first_name"] = result["given_name"]
    if "family_name" in result and "last_name" not in result:
        result["last_name"] = result["family_name"]
    return result


def _extract_user_id(payload: dict[str, Any]) -> str | None:
    """Pull the user_id string out of a payload dict, tolerating missing keys."""
    uid = payload.get("user_id")
    return str(uid) if uid else None


def _read_with_consumer_version(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Return the payload normalised for the active CONSUMER_VERSION.

    v1 consumer – reads event_data['first_name'] if present.
    v2 consumer – reads event_data['given_name'], falls back to first_name.
    """
    consumer = settings.CONSUMER_VERSION.lower()
    if consumer == "v2":
        # Tolerant reader: prefer v2 field names, fall back to v1
        working = upcast(payload)
        working.setdefault("given_name", working.get("first_name"))
        working.setdefault("family_name", working.get("last_name"))
        return working
    # Default v1 consumer – use payload as-is (reads first_name)
    return payload


# ── Aggregate upsert ──────────────────────────────────────────────────────────


def _upsert_aggregate(
    db: Session,
    user_id: str,
    event_type: str,
    event_ts: datetime,
) -> None:
    """
    Increment the daily UserEventAggregate counter using an UPSERT so that
    re-processing the same event is idempotent.
    """
    event_date: date = event_ts.date() if hasattr(event_ts, "date") else date.today()

    stmt = (
        pg_insert(UserEventAggregate)
        .values(
            user_id=user_id,
            event_type=event_type,
            count=1,
            last_seen=event_ts,
            date=event_date,
        )
        .on_conflict_do_update(
            constraint="uq_user_event_date",
            set_={
                "count": UserEventAggregate.count + 1,
                "last_seen": event_ts,
                "updated_at": datetime.now(timezone.utc),
            },
        )
    )
    db.execute(stmt)


# ── Main processing loop ──────────────────────────────────────────────────────


def process_events(batch_size: int | None = None) -> int:
    """
    Fetch up to ``batch_size`` unprocessed events and update aggregates.

    Returns the number of events successfully processed.
    """
    if batch_size is None:
        batch_size = settings.EVENT_BATCH_SIZE

    db: Session = SessionLocal()
    processed_count = 0

    try:
        stmt = (
            select(EventLog)
            .where(EventLog.processed.is_(False))
            .order_by(EventLog.created_at.asc())
            .limit(batch_size)
        )
        events = db.execute(stmt).scalars().all()

        for event in events:
            try:
                payload: dict[str, Any] = event.payload or {}
                normalised = _read_with_consumer_version(payload)
                user_id = _extract_user_id(normalised)

                if user_id:
                    _upsert_aggregate(
                        db,
                        user_id=user_id,
                        event_type=event.event_type,
                        event_ts=event.created_at,
                    )

                event.processed = True
                event.processing_error = None
                processed_count += 1

            except Exception as exc:  # noqa: BLE001
                logger.exception("Failed to process event %s: %s", event.id, exc)
                event.processing_error = str(exc)
                # Do not mark as processed – will be retried next cycle

        db.commit()

    except Exception:  # noqa: BLE001
        logger.exception("Unhandled error in process_events")
        db.rollback()
    finally:
        db.close()

    if processed_count:
        logger.info("Processed %d events (consumer=%s)", processed_count, settings.CONSUMER_VERSION)

    return processed_count
