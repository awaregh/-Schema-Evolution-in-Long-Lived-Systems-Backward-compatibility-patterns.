"""
Billing service – application entry point.

Routers
-------
* /api/v1/subscriptions  – manage billing subscriptions
* /api/v1/invoices       – manage invoices

Middleware
----------
* X-Schema-Version response header injected on every request.

Schema evolution demo
---------------------
The service demonstrates the integer→decimal type-change pattern:
  V1: amount_cents (Integer)
  V2: amount (Numeric 10,2) – dual-written alongside amount_cents during
      the expand phase so old and new clients can operate simultaneously.
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Request, Response
from sqlalchemy import func, select

from app.api.v1.billing import router as v1_router
from app.config import settings
from app.database import SessionLocal
from app.models.billing import Invoice, Subscription  # noqa: F401 – registers models

app = FastAPI(
    title="Billing Service",
    description="Schema Evolution research – Billing microservice",
    version=settings.SERVICE_VERSION,
)

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(v1_router)


# ── Middleware ────────────────────────────────────────────────────────────────


@app.middleware("http")
async def schema_version_header(request: Request, call_next) -> Response:
    """Attach X-Schema-Version and X-Response-Time to every response."""
    start = time.perf_counter()
    response: Response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Schema-Version"] = settings.SERVICE_VERSION
    response.headers["X-Response-Time"] = f"{elapsed_ms:.2f}ms"
    return response


# ── Top-level endpoints ───────────────────────────────────────────────────────


@app.get("/health", tags=["ops"])
def health() -> dict:
    return {"status": "ok", "version": settings.SERVICE_VERSION}


@app.get("/metrics", tags=["ops"])
def metrics() -> dict:
    """
    Lightweight operational metrics for schema-evolution research.

    Returns row counts split by schema_version so researchers can track
    progress of the integer→decimal type-change migration.
    """
    db = SessionLocal()
    try:
        sub_total = db.execute(
            select(func.count()).select_from(Subscription)
        ).scalar_one()
        sub_v1 = db.execute(
            select(func.count())
            .select_from(Subscription)
            .where(Subscription.schema_version == 1)
        ).scalar_one()
        sub_v2 = db.execute(
            select(func.count())
            .select_from(Subscription)
            .where(Subscription.schema_version == 2)
        ).scalar_one()

        inv_total = db.execute(
            select(func.count()).select_from(Invoice)
        ).scalar_one()
        inv_v1 = db.execute(
            select(func.count())
            .select_from(Invoice)
            .where(Invoice.schema_version == 1)
        ).scalar_one()
        inv_v2 = db.execute(
            select(func.count())
            .select_from(Invoice)
            .where(Invoice.schema_version == 2)
        ).scalar_one()
    finally:
        db.close()

    return {
        "subscriptions": {"total": sub_total, "v1_rows": sub_v1, "v2_rows": sub_v2},
        "invoices": {"total": inv_total, "v1_rows": inv_v1, "v2_rows": inv_v2},
    }
