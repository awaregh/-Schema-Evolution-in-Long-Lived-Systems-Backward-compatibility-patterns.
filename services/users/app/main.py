"""
Users service – application entry point.

Routers
-------
* /api/v1/users  – original schema (first_name / last_name)
* /api/v2/users  – evolved schema (given_name / family_name + dual-write)

Middleware
----------
* X-Schema-Version response header is injected on every request, reflecting
  the SERVICE_VERSION setting so clients can detect which version they are
  talking to.
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Request, Response
from sqlalchemy import func, select

from app.api.v1.users import router as v1_router
from app.api.v2.users import router as v2_router
from app.config import settings
from app.database import SessionLocal
from app.models.user import User  # noqa: F401 – registers model with Base

app = FastAPI(
    title="Users Service",
    description="Schema Evolution research – Users microservice",
    version=settings.SERVICE_VERSION,
)

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(v1_router)
app.include_router(v2_router)


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
    Lightweight operational metrics useful for schema-evolution research.

    Returns
    -------
    total_users  : all non-deleted users
    v1_rows      : rows last written by v1 logic (schema_version=1)
    v2_rows      : rows last written by v2 logic (schema_version=2)
    """
    db = SessionLocal()
    try:
        base_q = select(func.count()).select_from(User).where(User.deleted_at.is_(None))
        total = db.execute(base_q).scalar_one()

        v1_q = base_q.where(User.schema_version == 1)
        v1_rows = db.execute(v1_q).scalar_one()

        v2_q = base_q.where(User.schema_version == 2)
        v2_rows = db.execute(v2_q).scalar_one()
    finally:
        db.close()

    return {
        "total_users": total,
        "v1_rows": v1_rows,
        "v2_rows": v2_rows,
    }
