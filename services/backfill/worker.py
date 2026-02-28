"""
Backfill worker for Schema-Evolution research system.

Responsibilities
----------------
* Connect to PostgreSQL (via DATABASE_URL env var).
* Connect to Redis (via REDIS_URL env var) and subscribe to the
  ``backfill:trigger`` pub/sub channel so that an operator can fire a
  job on demand: ``PUBLISH backfill:trigger backfill_given_name``.
* Run the following jobs on a 60-second scheduler **and** on demand:

    backfill_given_name
        For every ``users`` row where ``given_name IS NULL`` and
        ``deleted_at IS NULL``, copy ``first_name → given_name`` and
        ``last_name → family_name``.  Sets ``schema_version = 2``.

    backfill_amount
        For every ``subscriptions`` row where ``amount IS NULL``, set
        ``amount = amount_cents / 100.0``.  Sets ``schema_version = 2``.

* Processes rows in batches of ``BATCH_SIZE`` (default 1 000) with a
  configurable inter-batch sleep to throttle I/O.
* Records each run in the ``backfill_jobs`` table (models.py).
* Handles ``SIGTERM`` / ``SIGINT`` for graceful shutdown.
* Reports per-job metrics: rows processed, elapsed time, error count.

Environment variables
---------------------
DATABASE_URL   PostgreSQL DSN (default: postgresql://admin:admin123@localhost:5432/schema_evolution)
REDIS_URL      Redis DSN     (default: redis://localhost:6379/0)
BATCH_SIZE     Rows per batch (default: 1000)
BATCH_SLEEP_S  Seconds to sleep between batches (default: 0.1)
SCHEDULE_S     Seconds between scheduled runs (default: 60)
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from datetime import datetime, timezone
from typing import Callable

import redis
import schedule
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from models import Base, BackfillJob

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql://admin:admin123@localhost:5432/schema_evolution",
)
REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
BATCH_SIZE: int = int(os.getenv("BATCH_SIZE", "1000"))
BATCH_SLEEP_S: float = float(os.getenv("BATCH_SLEEP_S", "0.1"))
SCHEDULE_S: int = int(os.getenv("SCHEDULE_S", "60"))
REDIS_CHANNEL: str = "backfill:trigger"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("backfill.worker")

# ---------------------------------------------------------------------------
# Graceful shutdown flag
# ---------------------------------------------------------------------------
_shutdown = threading.Event()


def _handle_signal(signum: int, _frame: object) -> None:
    log.info("Received signal %s – initiating graceful shutdown …", signum)
    _shutdown.set()


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    connect_args={"connect_timeout": 10},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _ensure_schema() -> None:
    """Create backfill_jobs table if it does not yet exist."""
    Base.metadata.create_all(bind=engine)
    log.info("backfill_jobs table is ready.")


# ---------------------------------------------------------------------------
# Job helpers
# ---------------------------------------------------------------------------

def _create_job_record(session: Session, job_name: str) -> BackfillJob:
    job = BackfillJob(
        job_name=job_name,
        status="running",
        rows_processed=0,
        started_at=datetime.now(timezone.utc),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def _finish_job(
    session: Session,
    job: BackfillJob,
    *,
    rows: int,
    error: str | None = None,
) -> None:
    job.rows_processed = rows
    job.status = "failed" if error else "completed"
    job.error_message = error
    job.completed_at = datetime.now(timezone.utc)
    session.commit()


def _count_pending(session: Session, query: str) -> int:
    result = session.execute(text(query))
    row = result.fetchone()
    return int(row[0]) if row else 0


# ---------------------------------------------------------------------------
# Job implementations
# ---------------------------------------------------------------------------

def backfill_given_name() -> None:
    """
    Copy first_name → given_name and last_name → family_name for all
    users rows where given_name IS NULL and deleted_at IS NULL.
    Processes rows in batches; sets schema_version = 2 on each updated row.
    """
    job_name = "backfill_given_name"
    log.info("[%s] Starting …", job_name)
    t0 = time.monotonic()
    total_rows = 0
    error_msg: str | None = None

    with SessionLocal() as session:
        job = _create_job_record(session, job_name)

        # Count outstanding rows once for progress reporting
        pending_count = _count_pending(
            session,
            "SELECT COUNT(*) FROM users WHERE given_name IS NULL AND deleted_at IS NULL",
        )
        job.rows_total = pending_count
        session.commit()
        log.info("[%s] %d rows need backfilling.", job_name, pending_count)

        try:
            while not _shutdown.is_set():
                result = session.execute(
                    text(
                        """
                        UPDATE users
                        SET    given_name     = first_name,
                               family_name    = last_name,
                               schema_version = 2,
                               updated_at     = NOW()
                        WHERE  id IN (
                            SELECT id FROM users
                            WHERE  given_name IS NULL
                              AND  deleted_at IS NULL
                            LIMIT  :batch_size
                            FOR UPDATE SKIP LOCKED
                        )
                        """
                    ),
                    {"batch_size": BATCH_SIZE},
                )
                session.commit()
                rows_this_batch = result.rowcount
                total_rows += rows_this_batch

                if rows_this_batch == 0:
                    # Nothing left to process
                    break

                log.info(
                    "[%s] Batch done – %d rows updated (total so far: %d).",
                    job_name,
                    rows_this_batch,
                    total_rows,
                )
                time.sleep(BATCH_SLEEP_S)

        except Exception as exc:  # noqa: BLE001
            error_msg = str(exc)
            log.exception("[%s] Unhandled error: %s", job_name, exc)
            session.rollback()
        finally:
            _finish_job(session, job, rows=total_rows, error=error_msg)

    elapsed = time.monotonic() - t0
    log.info(
        "[%s] Finished – rows_processed=%d elapsed=%.2fs error=%s",
        job_name,
        total_rows,
        elapsed,
        error_msg or "none",
    )


def backfill_amount() -> None:
    """
    Populate the ``amount`` (Numeric) column from ``amount_cents`` for all
    subscriptions rows where ``amount IS NULL``.
    Sets schema_version = 2 on each updated row.
    """
    job_name = "backfill_amount"
    log.info("[%s] Starting …", job_name)
    t0 = time.monotonic()
    total_rows = 0
    error_msg: str | None = None

    with SessionLocal() as session:
        job = _create_job_record(session, job_name)

        pending_count = _count_pending(
            session,
            "SELECT COUNT(*) FROM subscriptions WHERE amount IS NULL",
        )
        job.rows_total = pending_count
        session.commit()
        log.info("[%s] %d rows need backfilling.", job_name, pending_count)

        try:
            while not _shutdown.is_set():
                result = session.execute(
                    text(
                        """
                        UPDATE subscriptions
                        SET    amount         = ROUND(amount_cents / 100.0, 2),
                               schema_version = 2,
                               updated_at     = NOW()
                        WHERE  id IN (
                            SELECT id FROM subscriptions
                            WHERE  amount IS NULL
                            LIMIT  :batch_size
                            FOR UPDATE SKIP LOCKED
                        )
                        """
                    ),
                    {"batch_size": BATCH_SIZE},
                )
                session.commit()
                rows_this_batch = result.rowcount
                total_rows += rows_this_batch

                if rows_this_batch == 0:
                    break

                log.info(
                    "[%s] Batch done – %d rows updated (total so far: %d).",
                    job_name,
                    rows_this_batch,
                    total_rows,
                )
                time.sleep(BATCH_SLEEP_S)

        except Exception as exc:  # noqa: BLE001
            error_msg = str(exc)
            log.exception("[%s] Unhandled error: %s", job_name, exc)
            session.rollback()
        finally:
            _finish_job(session, job, rows=total_rows, error=error_msg)

    elapsed = time.monotonic() - t0
    log.info(
        "[%s] Finished – rows_processed=%d elapsed=%.2fs error=%s",
        job_name,
        total_rows,
        elapsed,
        error_msg or "none",
    )


# ---------------------------------------------------------------------------
# Job registry
# ---------------------------------------------------------------------------
JOB_REGISTRY: dict[str, Callable[[], None]] = {
    "backfill_given_name": backfill_given_name,
    "backfill_amount": backfill_amount,
}


# ---------------------------------------------------------------------------
# Redis pub/sub listener (runs in a background daemon thread)
# ---------------------------------------------------------------------------

def _redis_listener() -> None:
    """
    Subscribe to ``backfill:trigger`` on Redis.
    Messages must be the exact job name (e.g. ``backfill_given_name``).
    The job is executed synchronously in this thread so that the scheduler
    thread is not blocked.
    """
    log.info("Redis pub/sub listener starting (channel=%s) …", REDIS_CHANNEL)
    try:
        client = redis.from_url(REDIS_URL, decode_responses=True)
        pubsub = client.pubsub()
        pubsub.subscribe(REDIS_CHANNEL)

        for message in pubsub.listen():
            if _shutdown.is_set():
                break
            if message["type"] != "message":
                continue

            job_name: str = message["data"].strip()
            log.info("Redis trigger received: job_name=%r", job_name)

            fn = JOB_REGISTRY.get(job_name)
            if fn is None:
                log.warning("Unknown job name %r – ignoring.", job_name)
                continue

            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                log.exception("Redis-triggered job %r raised: %s", job_name, exc)

    except Exception as exc:  # noqa: BLE001
        log.warning("Redis listener failed (continuing without pub/sub): %s", exc)


# ---------------------------------------------------------------------------
# Scheduler setup
# ---------------------------------------------------------------------------

def _schedule_all_jobs() -> None:
    """Register every job to run on SCHEDULE_S cadence."""
    for job_name, fn in JOB_REGISTRY.items():
        schedule.every(SCHEDULE_S).seconds.do(fn)
        log.info("Scheduled %r every %d seconds.", job_name, SCHEDULE_S)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    log.info(
        "Backfill worker starting – BATCH_SIZE=%d BATCH_SLEEP_S=%.2f SCHEDULE_S=%d",
        BATCH_SIZE,
        BATCH_SLEEP_S,
        SCHEDULE_S,
    )

    _ensure_schema()
    _schedule_all_jobs()

    # Start Redis pub/sub listener in a daemon thread so it doesn't block shutdown
    listener_thread = threading.Thread(
        target=_redis_listener, name="redis-listener", daemon=True
    )
    listener_thread.start()

    # Run all jobs once immediately at startup so any outstanding rows are
    # picked up without waiting for the first scheduled interval.
    for job_name, fn in JOB_REGISTRY.items():
        if _shutdown.is_set():
            break
        log.info("Running initial pass for %r …", job_name)
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            log.exception("Initial run of %r raised: %s", job_name, exc)

    # Main scheduler loop
    log.info("Entering scheduler loop …")
    while not _shutdown.is_set():
        schedule.run_pending()
        time.sleep(1)

    log.info("Backfill worker stopped.")


if __name__ == "__main__":
    main()
