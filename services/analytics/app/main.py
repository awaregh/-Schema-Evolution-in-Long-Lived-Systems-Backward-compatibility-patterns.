"""
Analytics service – application entry point.

Routers
-------
* /api/v1/events      – event ingestion and listing
* /api/v1/aggregates  – pre-computed user-event aggregates
* /api/v1/stats       – system statistics

Background task
---------------
A lightweight scheduler runs process_events() every 30 seconds in a
background thread so events are continuously drained from the EventLog
and folded into UserEventAggregate counters.
"""

from __future__ import annotations

import logging
import threading
import time

from fastapi import FastAPI, Request, Response
from sqlalchemy import func, select

from app.api.v1.analytics import router as v1_router
from app.config import settings
from app.database import SessionLocal
from app.event_processor import process_events
from app.models.analytics import EventLog, UserEventAggregate  # noqa: F401

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Analytics Service",
    description="Schema Evolution research – Analytics microservice",
    version=settings.SERVICE_VERSION,
)

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(v1_router)


# ── Background event processor ────────────────────────────────────────────────

_processor_running = False


def _event_processor_loop(interval_seconds: int = 30) -> None:
    """Daemon thread that calls process_events() on a fixed schedule."""
    global _processor_running
    _processor_running = True
    logger.info(
        "Event processor started (interval=%ds, consumer=%s)",
        interval_seconds,
        settings.CONSUMER_VERSION,
    )
    while _processor_running:
        try:
            count = process_events()
            if count:
                logger.debug("Processor cycle: %d events processed", count)
        except Exception:  # noqa: BLE001
            logger.exception("Event processor cycle failed")
        time.sleep(interval_seconds)


@app.on_event("startup")
def start_background_processor() -> None:
    thread = threading.Thread(
        target=_event_processor_loop,
        kwargs={"interval_seconds": 30},
        daemon=True,
        name="event-processor",
    )
    thread.start()


@app.on_event("shutdown")
def stop_background_processor() -> None:
    global _processor_running
    _processor_running = False


# ── Middleware ────────────────────────────────────────────────────────────────


@app.middleware("http")
async def schema_version_header(request: Request, call_next) -> Response:
    start = time.perf_counter()
    response: Response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Schema-Version"] = settings.SERVICE_VERSION
    response.headers["X-Response-Time"] = f"{elapsed_ms:.2f}ms"
    return response


# ── Top-level endpoints ───────────────────────────────────────────────────────


@app.get("/health", tags=["ops"])
def health() -> dict:
    return {
        "status": "ok",
        "version": settings.SERVICE_VERSION,
        "consumer_version": settings.CONSUMER_VERSION,
    }


@app.get("/metrics", tags=["ops"])
def metrics() -> dict:
    """Lightweight metrics for schema-evolution research dashboards."""
    db = SessionLocal()
    try:
        total = db.execute(select(func.count()).select_from(EventLog)).scalar_one()
        processed = db.execute(
            select(func.count())
            .select_from(EventLog)
            .where(EventLog.processed.is_(True))
        ).scalar_one()
        errors = db.execute(
            select(func.count())
            .select_from(EventLog)
            .where(EventLog.processing_error.isnot(None))
        ).scalar_one()
        total_aggs = db.execute(
            select(func.count()).select_from(UserEventAggregate)
        ).scalar_one()
    finally:
        db.close()

    return {
        "total_events": total,
        "processed_events": processed,
        "unprocessed_events": total - processed,
        "error_events": errors,
        "total_aggregates": total_aggs,
        "consumer_version": settings.CONSUMER_VERSION,
    }
